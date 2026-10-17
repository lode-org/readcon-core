# Julia wrapper round trip.
#   julia julia_io.jl write BAND.txt DIR
#   julia julia_io.jl read  DIR BAND.txt
using ReadCon
using Printf

const ZSYM = Dict(
    1 => "H", 6 => "C", 8 => "O", 29 => "Cu", 78 => "Pt",
)

function sym_of(z::UInt64)
    get(ZSYM, Int(z), "X")
end

function z_of(sym::AbstractString)
    for (z, s) in ZSYM
        s == sym && return UInt64(z)
    end
    error("unknown symbol $sym")
end

function load_band(path)
    lines = readlines(path)
    i = 1
    parts = split(lines[i]); i += 1
    nframes = parse(Int, parts[2])
    frames = []
    for _ in 1:nframes
        @assert lines[i] == "FRAME"; i += 1
        natoms = parse(Int, split(lines[i])[2]); i += 1
        cell = parse.(Float64, split(lines[i])[2:4]); i += 1
        angles = parse.(Float64, split(lines[i])[2:4]); i += 1
        pbc = parse.(Int, split(lines[i])[2:4]); i += 1
        meta = length(lines[i]) > 5 ? lines[i][6:end] : ""; i += 1
        @assert lines[i] == "ATOMS"; i += 1
        atoms = []
        for _a in 1:natoms
            t = split(lines[i]); i += 1
            push!(atoms, (
                sym = t[1],
                x = parse(Float64, t[2]), y = parse(Float64, t[3]), z = parse(Float64, t[4]),
                id = parse(UInt64, t[5]), mass = parse(Float64, t[6]),
                fx = t[7] != "0", fy = t[8] != "0", fz = t[9] != "0",
                vx = parse(Float64, t[10]), vy = parse(Float64, t[11]), vz = parse(Float64, t[12]),
                hasv = t[13] != "0",
            ))
        end
        @assert lines[i] == "ENDFRAME"; i += 1
        push!(frames, (cell = cell, angles = angles, pbc = pbc, meta = meta, atoms = atoms))
    end
    return frames
end

function fmt(x)
    @sprintf("% .16e", x)
end

function store_band(path, frames)
    open(path, "w") do io
        println(io, "NFRAMES ", length(frames))
        for f in frames
            println(io, "FRAME")
            println(io, "NATOMS ", length(f.atoms))
            println(io, "CELL ", join(fmt.(f.cell), " "))
            println(io, "ANGLES ", join(fmt.(f.angles), " "))
            println(io, "PBC ", join(string.(f.pbc), " "))
            println(io, "META ", f.meta)
            println(io, "ATOMS")
            for a in f.atoms
                println(io, a.sym, " ", fmt(a.x), " ", fmt(a.y), " ", fmt(a.z), " ",
                        a.id, " ", fmt(a.mass), " ",
                        Int(a.fx), " ", Int(a.fy), " ", Int(a.fz), " ",
                        fmt(a.vx), " ", fmt(a.vy), " ", fmt(a.vz), " ", Int(a.hasv))
            end
            println(io, "ENDFRAME")
        end
    end
end

function pbc_of(meta::AbstractString)
    p = Int[-1, -1, -1]
    k = findfirst("\"pbc\"", meta)
    k === nothing && return p
    rest = meta[k[1]:end]
    n = 0
    i = 1
    while n < 3 && i <= lastindex(rest)
        if i + 3 <= lastindex(rest) && rest[i:i+3] == "true"
            n += 1; p[n] = 1; i += 4
        elseif i + 4 <= lastindex(rest) && rest[i:i+4] == "false"
            n += 1; p[n] = 0; i += 5
        else
            i = nextind(rest, i)
        end
    end
    return p
end

function do_write(band, dir)
    frames = load_band(band)
    mkpath(dir)
    open(joinpath(dir, "manifest.txt"), "w") do io
        println(io, length(frames))
    end
    for (i, f) in enumerate(frames)
        atoms = ReadCon.Atom[]
        anyv = any(a.hasv for a in f.atoms)
        for a in f.atoms
            push!(atoms, ReadCon.Atom(
                z_of(a.sym), a.x, a.y, a.z, a.id, a.mass,
                a.fx || a.fy || a.fz, (a.fx, a.fy, a.fz),
                a.vx, a.vy, a.vz, a.hasv,
                0.0, 0.0, 0.0, false,
                0.0, false,
            ))
        end
        cf = ReadCon.ConFrame(
            (f.cell[1], f.cell[2], f.cell[3]),
            (f.angles[1], f.angles[2], f.angles[3]),
            atoms, anyv,
            ("image $(i - 1)", ""), ("", ""),
            false, false, UInt32(3), f.meta,
            nothing, nothing, nothing, nothing, nothing, nothing,
        )
        path = joinpath(dir, @sprintf("frame_%03d.con", i - 1))
        write_con(path, [cf])
    end
end

function do_read(dir, band)
    n = parse(Int, strip(read(joinpath(dir, "manifest.txt"), String)))
    frames = []
    for i in 0:n-1
        path = joinpath(dir, @sprintf("frame_%03d.con", i))
        got = read_con(path)
        length(got) == 1 || error("expected one frame in $path")
        fr = got[1]
        meta = fr.metadata_json
        pbc = pbc_of(meta)
        atoms = []
        for a in fr.atoms
            push!(atoms, (
                sym = sym_of(a.atomic_number),
                x = a.x, y = a.y, z = a.z, id = a.atom_id, mass = a.mass,
                fx = a.fixed[1], fy = a.fixed[2], fz = a.fixed[3],
                vx = a.vx, vy = a.vy, vz = a.vz, hasv = a.has_velocity,
            ))
        end
        push!(frames, (cell = [fr.cell...], angles = [fr.angles...], pbc = pbc, meta = meta, atoms = atoms))
    end
    store_band(band, frames)
end

length(ARGS) == 3 || error("usage: julia_io.jl write|read SRC DST")
if ARGS[1] == "write"
    do_write(ARGS[2], ARGS[3])
elseif ARGS[1] == "read"
    do_read(ARGS[2], ARGS[3])
else
    error("mode must be write or read")
end
