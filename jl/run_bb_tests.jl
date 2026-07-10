#!/usr/bin/env julia
# run_bb_tests.jl — bootstrap block parity tests
# Called by parity_check.py with a test name.
include("bootstrap_block.jl")
using .DotMatrixBootstrap
using JSON

test = ARGS[1]

if test == "default_block_hex"
    bb = BootstrapBlock()
    println(bytes2hex(to_bytes(bb)))

elseif test == "parse_roundtrip"
    bb = BootstrapBlock()
    raw = to_bytes(bb)
    parsed = parse_block(raw)
    println(bytes2hex(to_bytes(parsed)))

elseif test == "decompose"
    bb = BootstrapBlock()
    results = []
    for addr in [0x0000, 0x1000, 0x1234, 0xFFFF, 0xABCD]
        t, c, idx = decompose_address(bb, addr)
        push!(results, Dict("addr" => string(addr, base=16, pad=4),
                            "tier" => string(t),
                            "cat"  => string(c),
                            "idx"  => string(idx)))
    end
    println(JSON.json(results))

else
    println("Unknown test: $test")
    exit(1)
end
