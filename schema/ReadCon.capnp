@0xb239fffe8de57842;

struct ConAtom {
  symbol     @0 :Text;
  x          @1 :Float64;
  y          @2 :Float64;
  z          @3 :Float64;
  isFixed    @4 :Bool;
  atomId     @5 :UInt64;
  vx         @6 :Float64;
  vy         @7 :Float64;
  vz         @8 :Float64;
  hasVelocity @9 :Bool;
}

struct ConFrameData {
  cell       @0 :List(Float64);
  angles     @1 :List(Float64);
  atoms      @2 :List(ConAtom);
  preboxHeader  @3 :List(Text);
  postboxHeader @4 :List(Text);
  hasVelocities @5 :Bool;
}

struct ParseRequest {
  fileContents @0 :Data;
}

struct ParseResult {
  frames @0 :List(ConFrameData);
}

struct WriteRequest {
  frames @0 :List(ConFrameData);
}

struct WriteResult {
  fileContents @0 :Data;
}

interface ReadConService {
  parseFrames @0 (req :ParseRequest) -> (result :ParseResult);
  writeFrames @1 (req :WriteRequest) -> (result :WriteResult);
}
