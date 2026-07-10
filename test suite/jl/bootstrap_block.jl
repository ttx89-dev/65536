"""
bootstrap_block.jl — reference implementation, 65535-point framework

Mirrors bootstrap_block.py field-for-field and byte-for-byte: same layout,
same checksums, same three-way read semantics. See the Python file's
module docstring for full rationale.

Standard library only — no Pkg dependencies, safe to run in any Julia
1.6+ environment without `Pkg.add`.

NOTE ON VALIDATION: this file was hand-verified against the Python
implementation's byte offsets and checksum logic, including the 0-index
to 1-index translation throughout, but it was NOT executed — no Julia
interpreter was available in the sandbox this was written in. Run it and
diff its printed hex/checksums against bootstrap_block.py's output
(hex should be identical, checksums should read 0x55 / 0xb8 for the
default block); if anything doesn't match, that mismatch is real
information and worth sending back.

Run with: julia bootstrap_block.jl
"""

module DotMatrixBootstrap

export BootstrapBlock, to_bytes, parse_block, decompose_address, read_slot,
       ChecksumAlgo, ALGO_NONE, ALGO_SUM8, ALGO_CRC16, ALGO_SHA256_TRUNC,
       ProvenanceScheme, ReadOutcome, BootstrapError

const MAGIC = UInt8[0x44, 0x4F, 0x54, 0x4D]          # "DOTM"
const PREAMBLE_SIZE = 12
const STRUCTURED_SIZE = 255
const BLOCK_SIZE = PREAMBLE_SIZE + STRUCTURED_SIZE    # 267
const RESERVED_SIZE = 244

@enum ChecksumAlgo::UInt8 begin
    ALGO_NONE = 0
    ALGO_SUM8 = 1
    ALGO_CRC16 = 2
    ALGO_SHA256_TRUNC = 3
end

@enum ProvenanceScheme::UInt8 begin
    PROV_NONE = 0
    PROV_HUMAN_CURATED = 1
    PROV_AGENT_SIGNED = 2
    PROV_CONTENT_HASH = 3
end

@enum ReadOutcome begin
    OUT_VALID
    OUT_UNASSIGNED
    OUT_DELETED
    # CORRUPT deliberately absent — see Python docstring: one checksum
    # covers the whole 267-byte block, not one per slot.
end

struct BootstrapError <: Exception
    msg::String
end
Base.showerror(io::IO, e::BootstrapError) = print(io, "BootstrapError: ", e.msg)

struct BootstrapBlock
    fw_ver_major::UInt8
    fw_ver_minor::UInt8
    address_width::UInt8
    tier_bits::UInt8
    category_bits::UInt8
    index_bits::UInt8
    reserved_preamble::UInt8
    schema_version::Tuple{UInt8,UInt8}
    key_version::Tuple{UInt8,UInt8}
    checksum_algo::ChecksumAlgo
    category_count::UInt8
    tier_count::UInt8
    headroom_ratio::UInt8
    tombstone_sentinel::UInt8
    provenance_scheme::ProvenanceScheme
    reserved_slots::Vector{UInt8}

    function BootstrapBlock(;
        fw_ver_major::Integer=1, fw_ver_minor::Integer=0,
        address_width::Integer=16, tier_bits::Integer=4,
        category_bits::Integer=4, index_bits::Integer=8,
        reserved_preamble::Integer=0,
        schema_version::Tuple{<:Integer,<:Integer}=(1, 0),
        key_version::Tuple{<:Integer,<:Integer}=(1, 0),
        checksum_algo::ChecksumAlgo=ALGO_SUM8,
        category_count::Integer=1, tier_count::Integer=1,
        headroom_ratio::Integer=10, tombstone_sentinel::Integer=0xFF,
        provenance_scheme::ProvenanceScheme=PROV_NONE,
        reserved_slots::Vector{UInt8}=zeros(UInt8, RESERVED_SIZE),
    )
        if tier_bits + category_bits + index_bits != address_width
            throw(BootstrapError("tier_bits + category_bits + index_bits != address_width"))
        end
        if address_width != 16
            throw(BootstrapError("only address_width=16 is supported in this version"))
        end
        if length(reserved_slots) != RESERVED_SIZE
            throw(BootstrapError("reserved_slots must be $RESERVED_SIZE bytes, got $(length(reserved_slots))"))
        end
        if !(0 <= headroom_ratio <= 100)
            throw(BootstrapError("headroom_ratio must be 0..100"))
        end

        new(UInt8(fw_ver_major), UInt8(fw_ver_minor), UInt8(address_width),
            UInt8(tier_bits), UInt8(category_bits), UInt8(index_bits),
            UInt8(reserved_preamble),
            (UInt8(schema_version[1]), UInt8(schema_version[2])),
            (UInt8(key_version[1]), UInt8(key_version[2])),
            checksum_algo, UInt8(category_count), UInt8(tier_count),
            UInt8(headroom_ratio), UInt8(tombstone_sentinel), provenance_scheme,
            reserved_slots)
    end
end

# ---- internal byte builders --------------------------------------------

function _preamble_body(b::BootstrapBlock)::Vector{UInt8}
    vcat(MAGIC, UInt8[b.fw_ver_major, b.fw_ver_minor, b.address_width,
                       b.tier_bits, b.category_bits, b.index_bits,
                       b.reserved_preamble])
end

_preamble_checksum(b::BootstrapBlock)::UInt8 = sum(_preamble_body(b)) % UInt8

function _structured_body(b::BootstrapBlock)::Vector{UInt8}
    fixed = UInt8[
        b.schema_version[1], b.schema_version[2],
        b.key_version[1], b.key_version[2],
        UInt8(b.checksum_algo),
        b.category_count, b.tier_count, b.headroom_ratio,
        b.tombstone_sentinel, UInt8(b.provenance_scheme),
    ]
    vcat(fixed, b.reserved_slots)
end

function _block_checksum(b::BootstrapBlock)::UInt8
    body = vcat(_preamble_body(b), UInt8[_preamble_checksum(b)], _structured_body(b))
    sum(body) % UInt8
end

# ---- public API ----------------------------------------------------------

function to_bytes(b::BootstrapBlock)::Vector{UInt8}
    block = vcat(_preamble_body(b), UInt8[_preamble_checksum(b)],
                 _structured_body(b), UInt8[_block_checksum(b)])
    @assert length(block) == BLOCK_SIZE "internal error: built $(length(block)) bytes, expected $BLOCK_SIZE"
    block
end

function parse_block(data::Vector{UInt8})::BootstrapBlock
    length(data) == BLOCK_SIZE || throw(BootstrapError("expected $BLOCK_SIZE bytes, got $(length(data))"))
    data[1:4] == MAGIC || throw(BootstrapError("bad magic: got $(data[1:4])"))

    computed_preamble_cs = sum(data[1:11]) % UInt8
    data[12] == computed_preamble_cs || throw(BootstrapError(
        "preamble checksum mismatch: stored=0x$(string(data[12], base=16, pad=2)) computed=0x$(string(computed_preamble_cs, base=16, pad=2))"))

    computed_block_cs = sum(data[1:266]) % UInt8
    data[267] == computed_block_cs || throw(BootstrapError(
        "block checksum mismatch: stored=0x$(string(data[267], base=16, pad=2)) computed=0x$(string(computed_block_cs, base=16, pad=2))"))

    BootstrapBlock(
        fw_ver_major=data[5], fw_ver_minor=data[6], address_width=data[7],
        tier_bits=data[8], category_bits=data[9], index_bits=data[10],
        reserved_preamble=data[11],
        schema_version=(data[13], data[14]),
        key_version=(data[15], data[16]),
        checksum_algo=ChecksumAlgo(data[17]),
        category_count=data[18], tier_count=data[19],
        headroom_ratio=data[20], tombstone_sentinel=data[21],
        provenance_scheme=ProvenanceScheme(data[22]),
        reserved_slots=data[23:266],
    )
end

function decompose_address(b::BootstrapBlock, address::Integer)
    max_addr = (1 << b.address_width) - 1
    (0 <= address <= max_addr) || throw(BootstrapError("address $address out of range for $(b.address_width)-bit space"))
    index = address & ((1 << b.index_bits) - 1)
    category = (address >> b.index_bits) & ((1 << b.category_bits) - 1)
    tier = (address >> (b.index_bits + b.category_bits)) & ((1 << b.tier_bits) - 1)
    (tier=tier, category=category, index=index)
end

function read_slot(b::BootstrapBlock, store::Vector{UInt8}, slot::Integer)
    (0 <= slot <= 0xFF) || throw(BootstrapError("slot $slot out of range 0..255"))
    if slot == 0x00
        return (OUT_VALID, UInt8(0))
    end
    offset = PREAMBLE_SIZE + (slot - 1)      # 0-indexed offset, matches Python exactly
    if offset + 1 > length(store)             # +1 converts to a 1-indexed bound check
        return (OUT_UNASSIGNED, nothing)
    end
    value = store[offset + 1]                 # Julia arrays are 1-indexed
    if slot != 0xFF && value == b.tombstone_sentinel
        return (OUT_DELETED, nothing)
    end
    if slot != 0xFF && value == 0x00
        return (OUT_UNASSIGNED, nothing)
    end
    return (OUT_VALID, value)
end

_hex(data::Vector{UInt8}) = join(string(x, base=16, pad=2) for x in data)

# ──────────────────────────────────────────────────────────────
# Self-test / demo
# ──────────────────────────────────────────────────────────────

function demo()
    b = BootstrapBlock()
    data = to_bytes(b)
    @assert length(data) == BLOCK_SIZE

    parsed = parse_block(data)
    @assert to_bytes(parsed) == data "round-trip failed"

    println("round-trip OK — ", length(data), " bytes")
    println("preamble checksum: 0x", string(_preamble_checksum(b), base=16, pad=2))
    println("block checksum:    0x", string(_block_checksum(b), base=16, pad=2))
    println("hex: ", _hex(data))

    # tamper detection — flip a byte inside "reserved" and confirm it's
    # still checksum-protected, matching bootstrap_block.py's test exactly
    # (Julia index 51 == Python index 50, since Julia is 1-indexed)
    tampered = copy(data)
    tampered[51] = xor(tampered[51], 0xFF)
    try
        parse_block(tampered)
        println("TAMPER TEST FAILED: corrupted block parsed without error")
    catch e
        println("tamper correctly rejected: ", e.msg)
    end

    for addr in (0x0000, 0x0001, 0x1234, 0xFFFF)
        d = decompose_address(b, addr)
        println("address 0x", string(addr, base=16, pad=4),
                " -> tier=", d.tier, " category=", d.category, " index=", d.index)
    end

    store = zeros(UInt8, PREAMBLE_SIZE + 256)
    store[1:BLOCK_SIZE] = data
    store[PREAMBLE_SIZE + 0x10] = 0xFF   # slot 0x10 tombstoned
    for slot in (0x01, 0x10, 0x50)
        outcome, val = read_slot(b, store, slot)
        vstr = val === nothing ? "" : " = 0x" * string(val, base=16, pad=2)
        println("slot 0x", string(slot, base=16, pad=2), ": ", outcome, vstr)
    end
end

end # module DotMatrixBootstrap

if abspath(PROGRAM_FILE) == @__FILE__
    DotMatrixBootstrap.demo()
end
