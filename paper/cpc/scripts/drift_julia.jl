# Julia binding drift over the CON conformance corpus and the header variants.
#
#   julia --project=julia/ReadCon paper/cpc/scripts/drift_julia.jl --list FILES
#   julia --project=julia/ReadCon paper/cpc/scripts/drift_julia.jl FILE...
#
# CSV columns: file,julia,sha_julia,rewrite_stable_julia
# sha_julia is the first 12 hex characters of SHA-256 of the rewritten text.
# A file the reader refuses is reject,-,-.

using ReadCon

function sha12(text::AbstractString)
    try
        @eval using SHA
        return bytes2hex(sha256(Vector{UInt8}(codeunits(text))))[1:12]
    catch
        path = tempname()
        write(path, text)
        hex = split(read(`sha256sum $path`, String))[1]
        rm(path; force=true)
        return String(hex)[1:12]
    end
end

function classify(path::String)
    frames = try
        read_con(path)
    catch
        return ("reject", "-", "-")
    end
    # An invalid file opens and then yields no frame. A legal empty
    # geometry still returns one frame, so "no frames" is the reject.
    if isempty(frames)
        return ("reject", "-", "-")
    end
    first = tempname() * ".con"
    second = tempname() * ".con"
    try
        write_con(first, frames)
        text = read(first, String)
        again = read_con(first)
        write_con(second, again)
        text2 = read(second, String)
        stable = text == text2 ? "yes" : "no"
        return ("accept", sha12(text), stable)
    catch err
        return ("accept", "error:" * string(typeof(err)), "no")
    finally
        rm(first; force=true)
        rm(second; force=true)
    end
end

function paths_from_args(args)
    if length(args) >= 2 && args[1] == "--list"
        return [String(strip(line)) for line in eachline(args[2]) if !isempty(strip(line))]
    end
    return args
end

function main()
    files = paths_from_args(ARGS)
    println("file,julia,sha_julia,rewrite_stable_julia")
    for path in files
        decision, digest, stable = classify(path)
        println(basename(path), ",", decision, ",", digest, ",", stable)
    end
end

main()
