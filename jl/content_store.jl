"""
content_store.jl — content-addressed variant, 65535-point framework

Mirrors content_store.py's architecture: addresses stop owning bytes and
start pointing at them, via a 64-bit FNV-1a content hash. See the Python
file's module docstring for the full rationale, including why what gets
hashed is dependency HASHES, not dependency ADDRESSES.

Depends on bootstrap_block.jl only — deliberately does NOT include
payload_codec.jl. The struct is named ContentStore to avoid collision with
payload_codec.jl's Store.

Standard library only — no Pkg dependencies.

Run with: julia -e 'include("content_store.jl")'
"""

using .DotMatrixBootstrap

const FNV_OFFSET = UInt64(0xcbf29ce484222325)
const FNV_PRIME = UInt64(0x100000001b3)

function fnv1a_64(data::Vector{UInt8})::UInt64
    h = FNV_OFFSET
    for byte in data
        h = xor(h, UInt64(byte))
        h = h * FNV_PRIME   # UInt64 multiply wraps mod 2^64 by default in Julia — exactly what FNV-1a requires
    end
    return h
end

const ADDR_DESC_SIZE = 9          # status(1) + hash(8)
const ADDRESS_SPACE = 1 << 16

const STATUS_UNASSIGNED = UInt8(0)
const STATUS_VALID = UInt8(1)
const STATUS_DELETED = UInt8(2)

@enum CAOutcome CA_VALID CA_UNASSIGNED CA_DELETED CA_CORRUPT

struct ContentStoreError <: Exception
    msg::String
end
Base.showerror(io::IO, e::ContentStoreError) = print(io, "ContentStoreError: ", e.msg)

_pack_u64(x::UInt64)::Vector{UInt8} = UInt8[(x>>(8*(7-i)))&0xFF for i in 0:7]
function _unpack_u64(d::AbstractVector{UInt8}, pos::Int)::UInt64
    r = UInt64(0)
    for i in 0:7
        r = (r << 8) | UInt64(d[pos+i])
    end
    r
end

mutable struct ContentRecord
    offset::Int
    length::Int
    refcount::Int
end

mutable struct ContentStore
    bootstrap::BootstrapBlock
    address_table::Vector{UInt8}
    content_table::Dict{UInt64, ContentRecord}
    hash_to_addresses::Dict{UInt64, Set{Int}}
    heap::Vector{UInt8}
end

ContentStore(bootstrap::BootstrapBlock) = ContentStore(bootstrap, zeros(UInt8, ADDRESS_SPACE * ADDR_DESC_SIZE),
                                                       Dict{UInt64,ContentRecord}(), Dict{UInt64,Set{Int}}(), UInt8[])

function compose_address(store::ContentStore, tier::Integer, category::Integer, index::Integer)::Int
    b = store.bootstrap
    (0 <= tier < (1 << b.tier_bits)) || throw(ContentStoreError("tier $tier out of range for $(b.tier_bits) tier bits"))
    (0 <= category < (1 << b.category_bits)) || throw(ContentStoreError("category $category out of range for $(b.category_bits) category bits"))
    (0 <= index < (1 << b.index_bits)) || throw(ContentStoreError("index $index out of range for $(b.index_bits) index bits"))
    (tier << (b.category_bits + b.index_bits)) | (category << b.index_bits) | index
end

function _get_address_descriptor(store::ContentStore, address::Integer)::Tuple{UInt8,UInt64}
    off = address * ADDR_DESC_SIZE + 1
    status = store.address_table[off]
    h = _unpack_u64(store.address_table, off + 1)
    return (status, h)
end

function _set_address_descriptor!(store::ContentStore, address::Integer, status::UInt8, h::UInt64)
    off = address * ADDR_DESC_SIZE + 1
    store.address_table[off] = status
    store.address_table[off+1:off+8] = _pack_u64(h)
end

function write_entry!(store::ContentStore, address::Integer, content::Vector{UInt8}, depends_on::Vector{<:Integer}=Int[])::UInt64
    b = store.bootstrap
    tier, category, _ = decompose_address(b, address)
    if tier == 0 && category == 0
        throw(ContentStoreError("address 0x$(string(address,base=16,pad=4)) is in the reserved bootstrap range (tier 0, category 0)"))
    end

    status, _ = _get_address_descriptor(store, address)
    if status != STATUS_UNASSIGNED
        throw(ContentStoreError("address 0x$(string(address,base=16,pad=4)) already written (status=$status); this reference build supports first-write only, not repointing"))
    end
    if length(depends_on) > 255
        throw(ContentStoreError("at most 255 dependencies per entry"))
    end

    dep_hashes = UInt64[]
    for dep_addr in depends_on
        outcome, _, _, dep_hash = read_entry(store, dep_addr)
        if outcome != CA_VALID
            throw(ContentStoreError("cannot write 0x$(string(address,base=16,pad=4)): dependency 0x$(string(dep_addr,base=16,pad=4)) is not VALID (outcome=$outcome)"))
        end
        push!(dep_hashes, dep_hash)
    end

    dep_bytes = UInt8[]
    for dh in dep_hashes
        append!(dep_bytes, _pack_u64(dh))
    end
    body = vcat(UInt8[length(dep_hashes)], dep_bytes, content)
    h = fnv1a_64(body)

    record = get(store.content_table, h, nothing)
    if record === nothing
        offset = length(store.heap)
        append!(store.heap, body)
        record = ContentRecord(offset, length(body), 0)
        store.content_table[h] = record
    end

    record.refcount += 1
    _set_address_descriptor!(store, address, STATUS_VALID, h)
    push!(get!(store.hash_to_addresses, h, Set{Int}()), Int(address))
    return h
end

function read_entry(store::ContentStore, address::Integer)
    status, h = _get_address_descriptor(store, address)
    status == STATUS_UNASSIGNED && return (CA_UNASSIGNED, nothing, nothing, nothing)
    status == STATUS_DELETED && return (CA_DELETED, nothing, nothing, nothing)

    record = get(store.content_table, h, nothing)
    record === nothing && return (CA_CORRUPT, nothing, nothing, nothing)

    body = store.heap[record.offset+1 : record.offset+record.length]
    if fnv1a_64(body) != h
        return (CA_CORRUPT, nothing, nothing, nothing)
    end

    dep_count = Int(body[1])
    dep_hashes = UInt64[]
    pos = 2
    for _ in 1:dep_count
        push!(dep_hashes, _unpack_u64(body, pos))
        pos += 8
    end
    content = body[pos:end]
    return (CA_VALID, content, dep_hashes, h)
end

function delete_entry!(store::ContentStore, address::Integer)
    status, h = _get_address_descriptor(store, address)
    if status == STATUS_UNASSIGNED
        throw(ContentStoreError("cannot delete 0x$(string(address,base=16,pad=4)): unassigned"))
    end
    if status == STATUS_VALID
        record = get(store.content_table, h, nothing)
        record !== nothing && (record.refcount -= 1)
        if haskey(store.hash_to_addresses, h)
            delete!(store.hash_to_addresses[h], Int(address))
        end
    end
    _set_address_descriptor!(store, address, STATUS_DELETED, h)
end

# ──────────────────────────────────────────────────────────────
# Self-test / demo — same sequence, same values as content_store.py,
# so the two outputs can be diffed by eye
# ──────────────────────────────────────────────────────────────

function demo()
    bootstrap = BootstrapBlock()
    store = ContentStore(bootstrap)

    addr_a = compose_address(store, 1, 1, 1)
    addr_b = compose_address(store, 1, 6, 1)

    h1 = write_entry!(store, addr_a, Vector{UInt8}(codeunits("walk")))
    size_after_first = length(store.heap)
    h2 = write_entry!(store, addr_b, Vector{UInt8}(codeunits("walk")))
    size_after_second = length(store.heap)

    println("addr_a=0x", string(addr_a,base=16,pad=4), " hash=", string(h1,base=16,pad=16))
    println("addr_b=0x", string(addr_b,base=16,pad=4), " hash=", string(h2,base=16,pad=16), "  same hash: ", h1 == h2)
    println("heap grew by ", size_after_second - size_after_first, " bytes on the duplicate write (expect 0)")
    println("refcount for shared content: ", store.content_table[h1].refcount, " (expect 2)")
    println("addresses currently pointing at it: ", sort(["0x" * string(a,base=16,pad=4) for a in store.hash_to_addresses[h1]]))

    rule_ed = compose_address(store, 1, 2, 1)
    write_entry!(store, rule_ed, Vector{UInt8}(codeunits("-ed")))

    walked_via_a = compose_address(store, 2, 1, 1)
    h_walked_a = write_entry!(store, walked_via_a, Vector{UInt8}(codeunits("walked")), [addr_a, rule_ed])

    walked_via_b = compose_address(store, 2, 6, 1)
    h_walked_b = write_entry!(store, walked_via_b, Vector{UInt8}(codeunits("walked")), [addr_b, rule_ed])

    println()
    println("walked-via-a hash=", string(h_walked_a,base=16,pad=16))
    println("walked-via-b hash=", string(h_walked_b,base=16,pad=16))
    println("same, despite different dependency SLOTS: ", h_walked_a == h_walked_b)

    delete_entry!(store, addr_a)
    println()
    println("refcount after deleting addr_a: ", store.content_table[h1].refcount, " (expect 1)")
    outcome, content, _, _ = read_entry(store, addr_b)
    println("addr_b still readable after addr_a deleted: ", outcome, " ", String(content))

    delete_entry!(store, addr_b)
    println("refcount after deleting addr_b too: ", store.content_table[h1].refcount, " (expect 0, eligible for future compaction)")

    try
        write_entry!(store, walked_via_a, Vector{UInt8}(codeunits("something else")))
        println("FAILED: repointing an already-VALID address was silently allowed")
    catch e
        println()
        println("correctly refused repoint: ", e.msg)
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    demo()
end
