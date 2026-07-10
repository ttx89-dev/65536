#!/usr/bin/env julia
# run_content_tests.jl — content store parity tests
# Called by parity_check.py with a test name.
include("bootstrap_block.jl")
include("content_store.jl")    # defines ContentStore, imports from DotMatrixBootstrap
using .DotMatrixBootstrap
using JSON

test = ARGS[1]

if test == "content_hash"
    data = hex2bytes(ARGS[2])
    h = fnv1a_64(data)
    println(string(h))

elseif test == "content_write_read"
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = compose_address(store, 1, 1, 0)
    data = UInt8[0x63, 0x6f, 0x6e, 0x74, 0x65, 0x6e, 0x74, 0x20, 0x70, 0x61, 0x72, 0x69, 0x74, 0x79]
    h = write_entry!(store, addr, data)
    outcome, payload, dep_hashes, hash = read_entry(store, addr)
    println(JSON.json(Dict(
        "hash"        => string("0x", lowercase(string(h, base=16, pad=16))),
        "payload_hex" => bytes2hex(payload),
        "outcome"     => string(Int(outcome))
    )))

else
    println("Unknown test: $test")
    exit(1)
end
