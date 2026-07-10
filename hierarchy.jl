"""
hierarchy.jl — tier and priority derivation, 65535-point framework

Mirrors hierarchy.py. Deliberately standalone — no dependency on
bootstrap_block.jl, payload_codec.jl, or content_store.jl, since this
operates purely on labels, before any address exists.

NOTE ON VALIDATION: hand-verified against hierarchy.py's logic, but NOT
executed — no Julia interpreter was available in the sandbox this was
written in.

Run with: julia hierarchy.jl
"""

struct HierarchyError <: Exception
    msg::String
end
Base.showerror(io::IO, e::HierarchyError) = print(io, "HierarchyError: ", e.msg)

function derive_tiers(items::Dict{String, Vector{String}})::Dict{String, Int}
    for (label, deps) in items
        for d in deps
            haskey(items, d) || throw(HierarchyError("$label depends on undefined $d"))
        end
    end

    tier = Dict{String, Int}()
    remaining = copy(items)
    while !isempty(remaining)
        ready = [label for (label, deps) in remaining if all(d -> haskey(tier, d), deps)]
        if isempty(ready)
            throw(HierarchyError("dependency cycle among: $(sort(collect(keys(remaining))))"))
        end
        for label in ready
            deps = remaining[label]
            tier[label] = isempty(deps) ? 0 : 1 + maximum(tier[d] for d in deps)
            delete!(remaining, label)
        end
    end
    return tier
end

function derive_priority(items::Dict{String, Vector{String}})::Dict{String, Int}
    direct_dependents = Dict{String, Vector{String}}(label => String[] for label in keys(items))
    for (label, deps) in items
        for d in deps
            haskey(items, d) || throw(HierarchyError("$label depends on undefined $d"))
            push!(direct_dependents[d], label)
        end
    end

    function transitive(label::String, seen::Set{String})
        for dependent in direct_dependents[label]
            if !(dependent in seen)
                push!(seen, dependent)
                transitive(dependent, seen)
            end
        end
        return seen
    end

    return Dict(label => length(transitive(label, Set{String}())) for label in keys(items))
end

struct IngestionPlan
    tier::Dict{String, Int}
    priority::Dict{String, Int}
    order::Vector{String}
end

function plan_ingestion(items::Dict{String, Vector{String}})::IngestionPlan
    tiers = derive_tiers(items)
    priority = derive_priority(items)
    order = sort(collect(keys(items)), by = l -> (tiers[l], -priority[l], l))
    return IngestionPlan(tiers, priority, order)
end

# ──────────────────────────────────────────────────────────────
# Self-test / demo — same subject, same values as hierarchy.py
# ──────────────────────────────────────────────────────────────

function demo()
    subject = Dict{String, Vector{String}}(
        "prime" => String[],
        "function_word" => String[],
        "root" => ["prime"],
        "affix" => ["prime"],
        "derivation_rule" => ["root", "affix"],
        "syntax_template" => ["root", "affix", "function_word"],
    )

    tiers = derive_tiers(subject)
    for label in sort(collect(keys(tiers)), by = l -> (tiers[l], l))
        println("tier ", tiers[label], ": ", label)
    end

    println()
    println("earlier, by hand, 'roots' and 'affixes' were placed at DIFFERENT tiers")
    println("(tier 1 and tier 2) purely by narrative feel, with no declared dependency")
    println("between them to justify it. Here, both genuinely depend only on 'prime',")
    println("so both land at tier ", tiers["root"], " — the hand-picked version was never wrong")
    println("exactly, just uncorroborated. this is what 'derived, not chosen' catches.")

    println()
    priority = derive_priority(subject)
    for label in sort(collect(keys(priority)), by = l -> -priority[l])
        println("priority ", priority[label], ": ", label, " (transitively relied on by ", priority[label], " other entries)")
    end

    println()
    plan = plan_ingestion(subject)
    println("suggested index-assignment order (tier ascending, then priority descending):")
    println("  ", plan.order)

    println()
    cyclic = Dict{String, Vector{String}}("a" => ["b"], "b" => ["a"])
    try
        derive_tiers(cyclic)
        println("FAILED: a real cycle was accepted")
    catch e
        println("cycle correctly rejected: ", e.msg)
    end

    println()
    dangling = Dict{String, Vector{String}}("a" => ["ghost"])
    try
        derive_tiers(dangling)
        println("FAILED: an undefined dependency was accepted")
    catch e
        println("undefined reference correctly rejected: ", e.msg)
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    demo()
end
