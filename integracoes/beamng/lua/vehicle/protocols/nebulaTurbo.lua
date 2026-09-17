-- Nebula: protocolo independente de pressao do turbo, somente para localhost.
-- API conferida em lua/vehicle/protocols.lua do BeamNG 0.39.4.
local M = {}
local sequence = 0
local psiPerBar = 14.503773773

function M.getAddress() return '127.0.0.1' end
function M.getPort() return 29878 end
function M.getMaxUpdateRate() return 20 end
function M.isPhysicsStepUsed() return false end
function M.getStructDefinition()
  return [[
    char magic[4];
    unsigned int version;
    unsigned int sequence;
    unsigned int flags;
    float turboBar;
    float maxTurboBar;
    float rpm;
    unsigned int afterfire;
  ]]
end

function M.fillStruct(packet, dtSim)
  packet.magic = 'NBTG'
  packet.version = 2
  packet.sequence = sequence
  sequence = (sequence + 1) % 4294967296
  packet.flags = 0
  local values = electrics and electrics.values
  if not values or values.rpm == nil or dtSim <= 0 then return end
  packet.flags = 1
  packet.rpm = values.rpm
  packet.afterfire = values.nebulaAfterfire or 0
  if values.turboBoost ~= nil then
    packet.flags = 3
    packet.turboBar = values.turboBoost / psiPerBar
    packet.maxTurboBar = (values.turboBoostMax or 0) / psiPerBar
  end
end

return M
