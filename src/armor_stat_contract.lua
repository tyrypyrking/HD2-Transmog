-- Test/reference formula facts from the current native Armor-card captures.
-- Production uses ArmorStatResolver's current-image semantic proof instead;
-- this pinned helper must not be an update-compatibility gate for the UI.
-- No native addresses/calls/reads, and no gameplay or ownership decisions.
-- The captured truncator references two small integer tables; their exact
-- values must accompany the current-image witness before this is certified.
local M={}
local TIMESTAMP=1790161983
local EVIDENCE='Armor UI scalar operands and float32 truncation/rounding, PE1790161983'
local function base()
 return {initial_value=100,speed_scale=5,armor_scale=50,one=1,zero=0,
  coefficients={armor_rating={0,1,2},speed={1.1,1,0.9},stamina_regen={0.75,1,1.5}},
  rounding='nearest_ties_away',verified=false,evidence=EVIDENCE}
end
function M.unverified()
 local value=base()
 value.missing_proof='Current-image low-bit mask and word-index table witness'
 return value
end
function M.for_image(timestamp,tables)
 if timestamp~=TIMESTAMP then return nil,'Armor stat formula has no verified evidence for this image'end
 if type(tables)~='table'or type(tables.masks)~='table'or type(tables.word_indices)~='table'then
  return nil,'Native truncation lookup-table evidence required'
 end
 if #tables.masks~=16 or #tables.word_indices~=2 then return nil,'Native truncation table size mismatch'end
 for i=1,16 do if tables.masks[i]~=2^(i-1)-1 then return nil,'Native truncation low-bit masks mismatch'end end
 if tables.word_indices[1]~=0 or tables.word_indices[2]~=1 then return nil,'Native truncation word indices mismatch'end
 local value=base();value.verified=true;value.image_timestamp=TIMESTAMP
 return value
end
return M
