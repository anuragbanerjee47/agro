import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final String baseUrl = "http://localhost:8000/api"; // Update to actual IP for physical device
  String activeProfile = "group1";
  Map<String, dynamic> dashboardData = {};
  bool isLoading = true;

  @override
  void initState() {
    super.initState();
    fetchDashboard();
  }

  Future<void> fetchDashboard() async {
    try {
      final response = await http.get(Uri.parse("$baseUrl/dashboard"));
      if (response.statusCode == 200) {
        setState(() {
          dashboardData = json.decode(response.body);
          activeProfile = dashboardData['active_profile'] ?? "group1";
          isLoading = false;
        });
      }
    } catch (e) {
      debugPrint("Error fetching dashboard: $e");
      setState(() => isLoading = false);
    }
  }

  Future<void> switchProfile(String groupKey) async {
    try {
      final response = await http.post(Uri.parse("$baseUrl/profile?group_key=$groupKey"));
      if (response.statusCode == 200) {
        setState(() => activeProfile = groupKey);
        await fetchDashboard();
      }
    } catch (e) {
      debugPrint("Error switching profile: $e");
    }
  }

  Widget buildMetricCard(String label, String value, String unit, Color color) {
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(label, style: const TextStyle(fontSize: 14, color: Colors.grey)),
            const SizedBox(height: 8),
            Text(
              "$value $unit",
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: color),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (isLoading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    final telemetry = dashboardData['telemetry'] as Map<String, dynamic>? ?? {};
    final analysis = dashboardData['analysis'] as Map<String, dynamic>? ?? {};
    final alerts = dashboardData['alerts'] as List<dynamic>? ?? [];
    final soilNpk = telemetry['soil_npk'] as List<dynamic>? ?? [0, 0, 0];

    return Scaffold(
      appBar: AppBar(
        title: const Text("Nutrient Monitor"),
        backgroundColor: Colors.green[700],
        foregroundColor: Colors.white,
        actions: [
          DropdownButton<String>(
            value: activeProfile,
            dropdownColor: Colors.green[600],
            underline: const SizedBox(),
            icon: const Icon(Icons.crop_rectangular, color: Colors.white),
            style: const TextStyle(color: Colors.white),
            onChanged: (String? newValue) {
              if (newValue != null) switchProfile(newValue);
            },
            items: [
              DropdownMenuItem(value: "group1", child: Text("Group 1: Wetland")),
              DropdownMenuItem(value: "group2", child: Text("Group 2: Cool Rabi")),
              DropdownMenuItem(value: "group3", child: Text("Group 3: Arid")),
              DropdownMenuItem(value: "group4", child: Text("Group 4: Cash Crop")),
            ],
          ),
          const SizedBox(width: 20),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: fetchDashboard,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Alerts Banner
            if (alerts.isNotEmpty)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                margin: const EdgeInsets.only(bottom: 20),
                decoration: BoxDecoration(
                  color: Colors.red[100],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.red),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: alerts.map((a) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Text("⚠️ $a", style: const TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
                  )).toList(),
                ),
              )
            else
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                margin: const EdgeInsets.only(bottom: 20),
                decoration: BoxDecoration(
                  color: Colors.green[100],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.green),
                ),
                child: const Text("✅ System Healthy - No alerts", style: TextStyle(color: Colors.green, fontWeight: FontWeight.bold)),
              ),

            const Text("Soil Metrics", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            GridView.count(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: 2,
              crossAxisSpacing: 10,
              mainAxisSpacing: 10,
              childAspectRatio: 1.5,
              children: [
                buildMetricCard("Nitrogen", "${analysis['nitrate'] ?? soilNpk[0]}", "PPM", Colors.blue),
                buildMetricCard("Phosphorus", "${analysis['phosphate'] ?? soilNpk[1]}", "PPM", Colors.orange),
                buildMetricCard("Potassium", "${soilNpk[2]}", "mg/kg", Colors.purple),
                buildMetricCard("pH Level", "${telemetry['ph'] ?? 'N/A'}", "", Colors.teal),
                buildMetricCard("Moisture", "${telemetry['moisture'] ?? 'N/A'}", "%", Colors.indigo),
                buildMetricCard("Soil Temp", "${telemetry['temperature'] ?? 'N/A'}", "°C", Colors.redAccent),
              ],
            ),
            const SizedBox(height: 20),
            const Text("Plant Diagnostics", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                leading: const Icon(Icons.thermostat, color: Colors.orange),
                title: Text("Canopy Temp: ${telemetry['canopy_temp'] ?? 'N/A'} °C"),
                subtitle: Text("Ambient Temp: ${telemetry['ambient_temp'] ?? 'N/A'} °C"),
              ),
            ),
            Card(
              child: ListTile(
                leading: const Icon(Icons.waves, color: Colors.blue),
                title: Text("Stem Piezo Vibration"),
                subtitle: Text("${telemetry['stem_piezo'] ?? 'N/A'} Hz"),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
