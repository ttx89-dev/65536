#!/usr/bin/env julia
# run_payload_tests.jl — payload codec parity tests
# Called by parity_check.py with a test name.
include("bootstrap_block.jl")
using .DotMatrixBootstrap
include("payload_codec.jl")
using JSON

test = ARGS[1]

if test == "payload_write_read_none"
    bb = BootstrapBlock(checksum_algo=ChecksumAlgo(0))
    store = Store(bb)
    addr = compose_address(store, 1, 1, 0)
    data = UInt8[0x68, 0x65, 0x6c, 0x6c, 0x6f, 0x20, 0x70, 0x61, 0x72, 0x69, 0x74, 0x79]
    write_entry!(store, addr, data)
    outcome, payload, deps = read_entry(store, addr)
    println(JSON.json(Dict(
        "addr"        => string(addr, base=16, pad=4),
        "outcome"     => string(Int(outcome)),
        "payload_hex" => bytes2hex(payload),
        "heap_growth" => string(length(store.heap))
    )))

elseif test == "payload_write_read_sum8"
    bb = BootstrapBlock(checksum_algo=ChecksumAlgo(1))
    store = Store(bb)
    addr = compose_address(store, 1, 1, 0)
    data = UInt8[0x68, 0x65, 0x6c, 0x6c, 0x6f, 0x20, 0x70, 0x61, 0x72, 0x69, 0x74, 0x79]
    write_entry!(store, addr, data)
    outcome, payload, deps = read_entry(store, addr)
    println(JSON.json(Dict(
        "addr"        => string(addr, base=16, pad=4),
        "outcome"     => string(Int(outcome)),
        "payload_hex" => bytes2hex(payload),
        "heap_growth" => string(length(store.heap))
    )))

else
    println("Unknown test: $test")
    exit(1)
end
