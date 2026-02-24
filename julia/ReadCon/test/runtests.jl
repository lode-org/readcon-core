using Test
using ReadCon

const TEST_DIR = joinpath(dirname(dirname(dirname(@__DIR__))), "resources", "test")

@testset "ReadCon.jl" begin
    @testset "Read .con file" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))
        @test length(frames) == 1
        frame = frames[1]
        @test frame.cell[1] ≈ 15.3456 atol=1e-4
        @test frame.angles[1] ≈ 90.0
        @test length(frame.atoms) == 4
        @test !frame.has_velocities
    end

    @testset "Read multi-frame .con" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_multi_cuh2.con"))
        @test length(frames) == 2
        @test length(frames[1].atoms) == 4
        @test length(frames[2].atoms) == 4
    end

    @testset "Read .convel file" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.convel"))
        @test length(frames) == 1
        frame = frames[1]
        @test frame.has_velocities
        atom = frame.atoms[1]
        @test atom.has_velocity
        @test atom.vx ≈ 0.001234 atol=1e-6
    end

    @testset "Read multi-frame .convel" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_multi_cuh2.convel"))
        @test length(frames) == 2
        @test frames[1].has_velocities
        @test frames[2].has_velocities
    end

    @testset "Error handling" begin
        @test_throws ErrorException read_con("/nonexistent/path.con")
    end

    @testset "Header strings" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))
        @test frames[1].prebox_header[1] == "Random Number Seed"
        @test frames[1].prebox_header[2] == "Time"
    end
end
