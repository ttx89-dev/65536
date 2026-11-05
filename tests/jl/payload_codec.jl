"""
payload_codec.jl — reference implementation, 65535-point framework

Mirrors payload_codec.py: descriptor table + heap, dependency-checked
writes, topological batch ordering, four-way read outcome. See the Python
file's module docstring for full architectural rationale.

Depends on bootstrap_block.jl (same directory). Standard library only —
no Pkg dependencies. Deliberately NOT wrapped in its own module — this is
a flat script, run directly, matching how it's actually used
(`julia payload_codec.jl`); the included bootstrap_block.jl keeps its own
module for reuse, this file just pulls its names into scope.

NOTE ON VALIDATION: hand-verified against payload_codec.py's logic and
byte offsets, including the 0-index/1-index translation, but NOT
executed — no Julia interpreter was available in the sandbox this was
written in. One thing that will legitimately differ from Python, by
design, not by bug: write_ordered!'s exact output order for entries that
are equally "ready" at the same point may not match Python's exactly,
because Julia's Dict does not preserve insertion order the way Python's
dict does (worked around here using explicit Vectors wherever order
matters, but tie-breaking among equally-ready items can still legitimately
differ). Both orders are valid topological orders — that's the actual
contract, not byte-identical ordering. The bootstrap block's checksums DO
need to match exactly; this does not.

Run with: julia payload_codec.jl
"""

include("bootstrap_block.jl")
using .DotMatrixBootstrap

const ADDRESS_SPACE = 1 << 16
const DESCRIPTOR_SIZE = 15   # status(1) + checksum(2) + length(4) + offset(8)

const STATUS_UNASSIGNED = UInt8(0)
const STATUS_VALID = UInt8(1)
const STATUS_DELETED = UInt8(2)

@enum EntryOutcome ENTRY_VALID ENTRY_UNASSIGNED ENTRY_DELETED ENTRY_CORRUPT
# distinct names from bootstrap_block.jl's OUT_VALID/OUT_UNASSIGNED/OUT_DELETED
# on purpose — a different, four-way outcome for per-entry checksums, not
# the bootstrap's whole-block outcome.

struct PayloadError <: Exception
    msg::String
end
Base.showerror(io::IO, e::PayloadError) = print(io, "PayloadError: ", e.msg)

# ---- manual big-endian pack/unpack (no external deps) ----------------------

_pack_u16(x::UInt16)::Vector{UInt8} = UInt8[(x >> 8) & 0xFF, x & 0xFF]
_unpack_u16(d::AbstractVector{UInt8}, pos::Int)::UInt16 = (UInt16(d[pos]) << 8) | UInt16(d[pos+1])

_pack_u32(x::UInt32)::Vector{UInt8} = UInt8[(x>>24)&0xFF, (x>>16)&0xFF, (x>>8)&0xFF, x&0xFF]
function _unpack_u32(d::AbstractVector{UInt8}, pos::Int)::UInt32
    (UInt32(d[pos])<<24) | (UInt32(d[pos+1])<<16) | (UInt32(d[pos+2])<<8) | UInt32(d[pos+3])
end

_pack_u64(x::UInt64)::Vector{UInt8} = UInt8[(x>>(8*(7-i)))&0xFF for i in 0:7]
function _unpack_u64(d::AbstractVector{UInt8}, pos::Int)::UInt64
    r = UInt64(0)
    for i in 0:7
        r = (r << 8) | UInt64(d[pos+i])
    end
    r
end

# ---- checksums --------------------------------------------------------------

function _crc16(data::Vector{UInt8})::UInt16
    crc::UInt16 = 0xFFFF
    poly::UInt16 = 0x1021
    for byte in data
        crc = xor(crc, UInt16(byte) << 8)
        for _ in 1:8
            crc = (crc & UInt16(0x8000)) != 0 ? xor(crc << 1, poly) : crc << 1
        end
    end
    return crc
end

function compute_checksum(data::Vector{UInt8}, algo::ChecksumAlgo)::UInt16
    if algo == ALGO_NONE
        return UInt16(0)
    elseif algo == ALGO_SUM8
        return UInt16(sum(data) % UInt8)
    elseif algo == ALGO_CRC16
        return _crc16(data)
    elseif algo == ALGO_SHA256_TRUNC
        throw(PayloadError("SHA256_TRUNC is not implemented in this reference build (both languages, on purpose)"))
    else
        throw(PayloadError("unknown checksum algo $algo"))
    end
end

# ---- store --------------------------------------------------------------------

struct Descriptor
    status::UInt8
    checksum::UInt16
    length::UInt32
    offset::UInt64
end

mutable struct Store
    bootstrap::BootstrapBlock
    descriptors::Vector{UInt8}
    heap::Vector{UInt8}
end

Store(bootstrap::BootstrapBlock) = Store(bootstrap, zeros(UInt8, ADDRESS_SPACE * DESCRIPTOR_SIZE), UInt8[])

function compose_address(store::Store, tier::Integer, category::Integer, index::Integer)::Int
    b = store.bootstrap
    (0 <= tier < (1 << b.tier_bits)) || throw(PayloadError("tier $tier out of range for $(b.tier_bits) tier bits"))
    (0 <= category < (1 << b.category_bits)) || throw(PayloadError("category $category out of range for $(b.category_bits) category bits"))
    (0 <= index < (1 << b.index_bits)) || throw(PayloadError("index $index out of range for $(b.index_bits) index bits"))
    (tier << (b.category_bits + b.index_bits)) | (category << b.index_bits) | index
end

function _get_descriptor(store::Store, address::Integer)::Descriptor
    off = address * DESCRIPTOR_SIZE + 1
    Descriptor(store.descriptors[off], _unpack_u16(store.descriptors, off+1),
               _unpack_u32(store.descriptors, off+3), _unpack_u64(store.descriptors, off+7))
end

function _set_descriptor!(store::Store, address::Integer, d::Descriptor)
    off = address * DESCRIPTOR_SIZE + 1
    store.descriptors[off] = d.status
    store.descriptors[off+1:off+2] = _pack_u16(d.checksum)
    store.descriptors[off+3:off+6] = _pack_u32(d.length)
    store.descriptors[off+7:off+14] = _pack_u64(d.offset)
end

function write_entry!(store::Store, address::Integer, content::Vector{UInt8}, depends_on::Vector{<:Integer}=Int[])
    b = store.bootstrap
    tier, category, _ = decompose_address(b, address)
    if tier == 0 && category == 0
        throw(PayloadError("address 0x$(string(address, base=16, pad=4)) is in the reserved bootstrap range (tier 0, category 0)"))
    end
    if length(depends_on) > 255
        throw(PayloadError("at most 255 dependencies per entry"))
    end

    for dep in depends_on
        outcome, _, _ = read_entry(store, dep)
        if outcome != ENTRY_VALID
            throw(PayloadError("cannot write 0x$(string(address, base=16, pad=4)): dependency 0x$(string(dep, base=16, pad=4)) is not VALID (outcome=$outcome)"))
        end
    end

    dep_bytes = UInt8[]
    for d in depends_on
        append!(dep_bytes, _pack_u16(UInt16(d)))
    end
    body = vcat(UInt8[length(depends_on)], dep_bytes, content)
    checksum = compute_checksum(body, b.checksum_algo)
    offset = length(store.heap)
    append!(store.heap, body)
    _set_descriptor!(store, address, Descriptor(STATUS_VALID, checksum, UInt32(length(body)), UInt64(offset)))
    nothing
end

function read_entry(store::Store, address::Integer)
    d = _get_descriptor(store, address)
    d.status == STATUS_UNASSIGNED && return (ENTRY_UNASSIGNED, nothing, nothing)
    d.status == STATUS_DELETED && return (ENTRY_DELETED, nothing, nothing)

    body = store.heap[d.offset+1 : d.offset+d.length]
    if compute_checksum(body, store.bootstrap.checksum_algo) != d.checksum
        return (ENTRY_CORRUPT, nothing, nothing)
    end

    dep_count = Int(body[1])
    deps = Int[]
    pos = 2
    for _ in 1:dep_count
        push!(deps, Int(_unpack_u16(body, pos)))
        pos += 2
    end
    content = body[pos:end]
    return (ENTRY_VALID, content, deps)
end

function delete_entry!(store::Store, address::Integer)
    d = _get_descriptor(store, address)
    if d.status == STATUS_UNASSIGNED
        throw(PayloadError("cannot delete 0x$(string(address, base=16, pad=4)): unassigned"))
    end
    _set_descriptor!(store, address, Descriptor(STATUS_DELETED, d.checksum, d.length, d.offset))
    nothing
end

function write_ordered!(store::Store, items::Vector{<:Tuple})
    order_seen = Int[]
    by_addr = Dict{Int, Tuple{Vector{UInt8}, Vector{Int}}}()
    for (addr, content, deps) in items
        haskey(by_addr, addr) && throw(PayloadError("address 0x$(string(addr, base=16, pad=4)) appears twice in one batch"))
        by_addr[addr] = (Vector{UInt8}(content), Vector{Int}(deps))
        push!(order_seen, addr)
    end

    in_degree = Dict{Int,Int}()
    dependents = Dict{Int, Vector{Int}}(a => Int[] for a in order_seen)
    for addr in order_seen
        _, deps = by_addr[addr]
        pending = [d for d in deps if haskey(by_addr, d)]
        in_degree[addr] = length(pending)
        for d in pending
            push!(dependents[d], addr)
        end
        for d in deps
            if !haskey(by_addr, d)
                outcome, _, _ = read_entry(store, d)
                if outcome != ENTRY_VALID
                    throw(PayloadError("batch item 0x$(string(addr,base=16,pad=4)) depends on 0x$(string(d,base=16,pad=4)), outside this batch and not VALID (outcome=$outcome)"))
                end
            end
        end
    end

    ready = [a for a in order_seen if in_degree[a] == 0]
    order = Int[]
    while !isempty(ready)
        a = pop!(ready)
        push!(order, a)
        for dep_addr in dependents[a]
            in_degree[dep_addr] -= 1
            in_degree[dep_addr] == 0 && push!(ready, dep_addr)
        end
    end

    if length(order) != length(by_addr)
        remaining = sort([a for a in order_seen if !(a in order)])
        throw(PayloadError("dependency cycle among: $([string(a,base=16,pad=4) for a in remaining])"))
    end

    for addr in order
        content, deps = by_addr[addr]
        write_entry!(store, addr, content, deps)
    end
    return order
end

# ──────────────────────────────────────────────────────────────
# Self-test / demo
# ──────────────────────────────────────────────────────────────

function demo()
    bootstrap = BootstrapBlock()
    store = Store(bootstrap)

    rule_ed = compose_address(store, 1, 2, 1)
    root_walk = compose_address(store, 1, 1, 1)
    walked = compose_address(store, 2, 1, 1)
    println("addresses: rule_ed=0x", string(rule_ed,base=16,pad=4),
            " root_walk=0x", string(root_walk,base=16,pad=4),
            " walked=0x", string(walked,base=16,pad=4))

    try
        write_entry!(store, walked, Vector{UInt8}(codeunits("walked")), [root_walk, rule_ed])
        println("FAILED: wrote an entry whose dependencies don't exist yet")
    catch e
        println("correctly refused premature write: ", e.msg)
    end

    write_entry!(store, rule_ed, Vector{UInt8}(codeunits("-ed")))
    write_entry!(store, root_walk, Vector{UInt8}(codeunits("walk")))
    write_entry!(store, walked, Vector{UInt8}(codeunits("walked")), [root_walk, rule_ed])
    println("wrote all three in dependency order")

    outcome, content, deps = read_entry(store, walked)
    println("read walked: ", outcome, " content=", String(content), " deps=", [string(d,base=16,pad=4) for d in deps])

    delete_entry!(store, root_walk)
    outcome, _, _ = read_entry(store, root_walk)
    println("read root_walk after delete: ", outcome)

    d = _get_descriptor(store, walked)
    store.heap[d.offset + 1] = xor(store.heap[d.offset + 1], 0xFF)
    outcome, content, _ = read_entry(store, walked)
    println("read walked after corruption: ", outcome, " content=", content)

    untouched = compose_address(store, 5, 5, 5)
    outcome, _, _ = read_entry(store, untouched)
    println("read never-written address: ", outcome)

    prefix_re = compose_address(store, 1, 3, 1)
    prefix_un = compose_address(store, 1, 3, 2)
    root_do = compose_address(store, 1, 1, 3)
    redo = compose_address(store, 2, 1, 3)
    undo = compose_address(store, 2, 1, 4)
    order = write_ordered!(store, [
        (redo, codeunits("redo"), [prefix_re, root_do]),
        (undo, codeunits("undo"), [prefix_un, root_do]),
        (root_do, codeunits("do"), Int[]),
        (prefix_un, codeunits("un-"), Int[]),
        (prefix_re, codeunits("re-"), Int[]),
    ])
    println("batch submitted unordered, written in dependency order:")
    println("  ", [string(a,base=16,pad=4) for a in order])

    cyc_a = compose_address(store, 3, 3, 1)
    cyc_b = compose_address(store, 3, 3, 2)
    try
        write_ordered!(store, [
            (cyc_a, codeunits("a"), [cyc_b]),
            (cyc_b, codeunits("b"), [cyc_a]),
        ])
        println("FAILED: a real dependency cycle was accepted")
    catch e
        println("cycle correctly rejected: ", e.msg)
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    demo()
end
