using GameReaderCommon;
using SimHub.Plugins;
using System;
using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Windows.Media;

namespace NebulaSimHub
{
    [PluginDescription("Envia RPM do BeamNG.drive, Assetto Corsa e outros jogos para as luzes da Nebula.")]
    [PluginAuthor("Nebula")]
    [PluginName("Nebula RPM Telemetry")]
    public sealed class NebulaSimHubPlugin : IPlugin, IDataPlugin
    {
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private readonly IPEndPoint destination = new IPEndPoint(IPAddress.Loopback, 29876);
        private UdpClient udp;
        private uint sequence;
        private long nextSendMilliseconds;
        private string lastGame = "simhub";

        public PluginManager PluginManager { get; set; }
        public string LeftMenuTitle => null;
        public ImageSource PictureIcon => null;

        public void Init(PluginManager pluginManager)
        {
            PluginManager = pluginManager;
            udp = new UdpClient(AddressFamily.InterNetwork);
            udp.Client.Blocking = false;
        }

        public void End(PluginManager pluginManager)
        {
            Send(false, 0, 0, 0, 0, 0, 1, false, 0, double.NaN, double.NaN, double.NaN, 0, 0, 0);
            udp?.Dispose();
            udp = null;
        }

        public void DataUpdate(PluginManager pluginManager, ref GameData data)
        {
            long now = clock.ElapsedMilliseconds;
            if (now < nextSendMilliseconds)
            {
                return;
            }
            nextSendMilliseconds = now + 33;

            try
            {
                if (!data.GameRunning || data.NewData == null)
                {
                    Send(false, 0, 0, 0, 0, 0, 1, false, 0, double.NaN, double.NaN, double.NaN, 0, 0, 0);
                    return;
                }
                lastGame = SafeSource(data.GameName);
                double rpm = data.NewData.Rpms;
                double maxRpm = data.NewData.MaxRpm;
                if (!IsFinite(rpm) || !IsFinite(maxRpm) || maxRpm < 500 || maxRpm > 40000)
                {
                    Send(false, 0, 0, 0, 0, 0, 1, false, 0, double.NaN, double.NaN, double.NaN, 0, 0, 0);
                    return;
                }
                double throttle = Math.Max(0, Math.Min(1, data.NewData.Throttle / 100.0));
                int gear = ParseGear(data.NewData.Gear);
                bool shifting = data.OldData != null && data.OldData.Gear != data.NewData.Gear;
                double speedKmh = SafeRange(data.NewData.SpeedKmh, 0, 1000);
                // BeamNG preenche Turbo (em bar), mas deixa TurboBar sempre em zero.
                // Nos outros jogos mantemos TurboBar como primeira opcao.
                double turboBar = SafeOptional(
                    string.Equals(lastGame, "beamngdrive", StringComparison.OrdinalIgnoreCase)
                        ? data.NewData.Turbo
                        : data.NewData.TurboBar,
                    -5,
                    20);
                // O stream do BeamNG nao fornece pressao de oleo ao SimHub. Zero
                // nesse caso significa "indisponivel", nao pressao real.
                double oilPressure = string.Equals(lastGame, "beamngdrive", StringComparison.OrdinalIgnoreCase)
                    ? double.NaN
                    : SafeOptional(data.NewData.OilPressure, -1, 50);
                double oilTemperature = SafeOptional(data.NewData.OilTemperature, -100, 300);
                double fuelPercent = SafeRange(data.NewData.FuelPercent, 0, 100);
                double waterTemp = SafeRange(data.NewData.WaterTemperature, -100, 300);
                int engineMap = Math.Max(0, Math.Min(99, data.NewData.EngineMap));
                Send(true, rpm, 0, maxRpm, maxRpm, throttle, gear, shifting, speedKmh, turboBar, oilPressure, oilTemperature, fuelPercent, waterTemp, engineMap);
            }
            catch
            {
                Send(false, 0, 0, 0, 0, 0, 1, false, 0, double.NaN, double.NaN, double.NaN, 0, 0, 0);
            }
        }

        private void Send(
            bool valid,
            double rpm,
            double minRpm,
            double redlineRpm,
            double maxRpm,
            double gas,
            int gear,
            bool shifting,
            double speedKmh,
            double turboBar,
            double oilPressure,
            double oilTemperature,
            double fuelPercent,
            double waterTemp,
            int engineMap)
        {
            if (udp == null)
            {
                return;
            }
            string json = string.Format(
                CultureInfo.InvariantCulture,
                "{{\"v\":2,\"seq\":{0},\"source\":\"{1}\",\"metric\":\"rpm\",\"valid\":{2},\"rpm\":{3:F2},\"min_rpm\":{4:F2},\"redline_rpm\":{5:F2},\"max_rpm\":{6:F2},\"gas\":{7:F4},\"gear\":{8},\"shifting\":{9},\"drag\":false,\"speed_kmh\":{10:F2},\"turbo_bar\":{11},\"oil_pressure\":{12},\"oil_temp\":{13},\"fuel_percent\":{14:F2},\"water_temp\":{15:F2},\"engine_map\":{16}}}",
                sequence++,
                lastGame,
                valid ? "true" : "false",
                rpm,
                minRpm,
                redlineRpm,
                maxRpm,
                gas,
                gear,
                shifting ? "true" : "false",
                speedKmh,
                JsonNumber(turboBar),
                JsonNumber(oilPressure),
                JsonNumber(oilTemperature),
                fuelPercent,
                waterTemp,
                engineMap);
            byte[] payload = Encoding.UTF8.GetBytes(json);
            try
            {
                udp.Send(payload, payload.Length, destination);
            }
            catch (SocketException)
            {
                // UDP local é melhor esforço; o loop seguinte tenta novamente.
            }
            catch (ObjectDisposedException)
            {
            }
        }

        private static bool IsFinite(double value)
        {
            return !double.IsNaN(value) && !double.IsInfinity(value);
        }

        private static double SafeRange(double value, double minimum, double maximum)
        {
            return IsFinite(value) ? Math.Max(minimum, Math.Min(maximum, value)) : 0;
        }

        private static double SafeOptional(double value, double minimum, double maximum)
        {
            return IsFinite(value) && value >= minimum && value <= maximum ? value : double.NaN;
        }

        private static string JsonNumber(double value)
        {
            return IsFinite(value)
                ? value.ToString("F3", CultureInfo.InvariantCulture)
                : "null";
        }

        private static int ParseGear(string gear)
        {
            if (string.Equals(gear, "R", StringComparison.OrdinalIgnoreCase)) return 0;
            if (string.Equals(gear, "N", StringComparison.OrdinalIgnoreCase)) return 1;
            int parsed;
            return int.TryParse(gear, out parsed) ? Math.Max(2, Math.Min(9, parsed + 1)) : 1;
        }

        private static string SafeSource(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return "simhub";
            var builder = new StringBuilder(64);
            foreach (char character in name.ToLowerInvariant())
            {
                if (builder.Length == 64) break;
                builder.Append(char.IsLetterOrDigit(character) || character == '_' || character == '-' ? character : '_');
            }
            return builder.Length == 0 ? "simhub" : builder.ToString();
        }
    }
}
