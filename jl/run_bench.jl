#!/usr/bin/env julia
"""
run_bench.jl — Julia performance benchmarks, 65535-point framework
═══════════════════════════════════════════════════════════════════════════════

Mirrors bench_performance.py hot paths. Called by bench_cross_language.py.
Runs each benchmark case N_TRIALS internally (warmup first) and outputs
JSON timing stats for all cases.

Standard library + JSON only — no Pkg dependencies.
═══════════════════════════════════════════════════════════════════════════════
"""

include("bootstrap_block.jl")
include("payload_codec.jl")
include("content_store.jl")
using .DotMatrixBootstrap
using JSON

const N_WARMUP = 5
const N_TRIALS = 50


"""
    timed(f)

Run f() with N_WARMUP warmup calls, then N_TRIALS timed calls.
Returns dict with min/p50/p95/max/mean in microseconds.
"""
function timed(f)
    for _ in 1:N_WARMUP
        f()
    end
    elapsed = Float64[]
    for _ in 1:N_TRIALS
        t0 = time_ns()
        f()
        push!(elapsed, (time_ns() - t0) / 1e9)
    end
    sort!(elapsed)
    n = length(elapsed)
    return Dict(
        "min_us"  => round(elapsed[1] * 1e6, digits=2),
        "p50_us"  => round(elapsed[div(n, 2)] * 1e6, digits=2),
        "p95_us"  => round(elapsed[min(n, max(1, Int(floor(n * 0.95))))] * 1e6, digits=2),
        "max_us"  => round(elapsed[end] * 1e6, digits=2),
        "mean_us" => round(sum(elapsed) / n * 1e6, digits=2),
        "trials"  => n,
    )
end


# ═══════════════════════════════════════════════════════════════════════════
# Bootstrap Block Benchmarks
# ═══════════════════════════════════════════════════════════════════════════

bb = BootstrapBlock()
bench_results = Dict{String,Any}()

bench_results["bootstrap_serialize"] = timed(() -> DotMatrixBootstrap.to_bytes(bb))

data = DotMatrixBootstrap.to_bytes(bb)
bench_results["bootstrap_parse"] = timed(() -> parse_block(data))

addrs = [0x0000, 0x0001, 0x1234, 0xABCD, 0xFFFF]
bench_results["bootstrap_decompose"] = timed(() -> begin
    for a in addrs
        decompose_address(bb, a)
    end
end)


# ═══════════════════════════════════════════════════════════════════════════
# Payload Store Benchmarks (NONE checksum)
# ═══════════════════════════════════════════════════════════════════════════

BB_NONE = BootstrapBlock(checksum_algo=ChecksumAlgo(0))
TEMPLATE_STORE = Store(BB_NONE)

for (sname, size) in [("64B", 64), ("1KB", 1024), ("64KB", 65536)]
    content = zeros(UInt8, size)
    addr_val = compose_address(TEMPLATE_STORE, 1, 1, 0x10)

    # Write: fresh store per call
    let bb_n = BB_NONE, a = addr_val, c = content
        bench_results["payload_write_nonce_$(sname)"] = timed(() -> begin
            s = Store(bb_n)  # from payload_codec.jl via DotMatrixBootstrap
            write_entry!(s, a, c)
        end)
    end

    # Read: set up store once, read many
    let bb_n = BB_NONE, a = addr_val, c = content
        s_read = Store(bb_n)
        write_entry!(s_read, a, c)
        bench_results["payload_read_nonce_$(sname)"] = timed(() -> read_entry(s_read, a))
    end
end


# ═══════════════════════════════════════════════════════════════════════════
# Content Store Benchmarks
# ═══════════════════════════════════════════════════════════════════════════

BB_DEF = BootstrapBlock()

for (sname, size) in [("64B", 64), ("1KB", 1024), ("64KB", 65536)]
    content = zeros(UInt8, size)

    # Write: fresh store + address per call
    let c = content
        bench_results["content_write_$(sname)"] = timed(() -> begin
            s = ContentStore(BootstrapBlock())
            a = compose_address(s, 1, 1, 0x20)
            write_entry!(s, a, c)
        end)
    end

    # Read: fresh store, write once, read
    let c = content
        bench_results["content_read_$(sname)"] = timed(() -> begin
            s = ContentStore(BootstrapBlock())
            a = compose_address(s, 1, 1, 0x20)
            write_entry!(s, a, c)
            read_entry(s, a)
        end)
    end
end


println(JSON.json(bench_results))
