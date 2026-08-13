# Cap'n Proto wire schema for CON frame transfer (RPC and process boundaries).
# Mirrors CON v2–v3 semantics in src/types.rs (AtomDatum + FrameHeader).
# Text .con remains the on-disk interchange authority; this schema is not bcon.
@0xb239fffe8de57842;

# One atom in type-grouped order (matches ConFrame.atom_data).
struct ConAtom {
  symbol @0 :Text;
  x @1 :Float64;
  y @2 :Float64;
  z @3 :Float64;
  # Column-4 style bitmask 0–7 (bit0=x, bit1=y, bit2=z). Encoder uses
  # encode_fixed_bitmask (canonical 7 for all-fixed, never legacy 1).
  fixedMask @4 :UInt8;
  atomId @5 :UInt64;

  hasVelocity @6 :Bool;
  vx @7 :Float64;
  vy @8 :Float64;
  vz @9 :Float64;

  hasForce @10 :Bool;
  fx @11 :Float64;
  fy @12 :Float64;
  fz @13 :Float64;

  hasEnergy @14 :Bool;
  energy @15 :Float64;

  hasCharge @16 :Bool;
  charge @17 :Float64;

  hasSpin @18 :Bool;
  spin @19 :Float64;

  hasMagmom @20 :Bool;
  mx @21 :Float64;
  my @22 :Float64;
  mz @23 :Float64;
}

# One complete frame: header fields + atoms + section presence + metadata.
struct ConFrameData {
  cell @0 :List(Float64);           # length 3
  angles @1 :List(Float64);         # length 3
  atoms @2 :List(ConAtom);
  # prebox: [user_line, metadata_json_line]; postbox: reserved lines 5–6
  preboxHeader @3 :List(Text);
  postboxHeader @4 :List(Text);
  hasVelocities @5 :Bool;
  specVersion @6 :UInt32 = 2;

  hasForces @7 :Bool;
  hasEnergies @8 :Bool;
  hasCharges @9 :Bool;
  hasSpins @10 :Bool;
  hasMagmoms @11 :Bool;

  massesPerType @12 :List(Float64);
  natmsPerType @13 :List(UInt32);
  # Declared section names (JSON sections array), lower-case wire names
  sections @14 :List(Text);
  # Full JSON object for free-form + reserved keys (may be empty "{}")
  metadataJson @15 :Text;
  strictValidation @16 :Bool;
  sectionsDeclared @17 :Bool;
  # User free-form line 1 only (also first preboxHeader entry when present)
  preboxUser @18 :Text;
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
