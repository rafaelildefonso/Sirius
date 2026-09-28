import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../application/geofence_manager.dart';
import '../../../core/storage/database/database.dart';
import '../../../core/storage/repositories/place_visit_repository.dart';

class PlacesScreen extends ConsumerStatefulWidget {
  const PlacesScreen({super.key});

  @override
  ConsumerState<PlacesScreen> createState() => _PlacesScreenState();
}

class _PlacesScreenState extends ConsumerState<PlacesScreen>
    with SingleTickerProviderStateMixin {
  final _nameController = TextEditingController();
  final _radiusController = TextEditingController(text: '100');
  final _mapController = MapController();
  LatLng? _selectedPosition;
  late TabController _tabController;
  late PlaceVisitRepository _visitRepo;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _visitRepo = PlaceVisitRepository(AppDatabase());
  }

  @override
  void dispose() {
    _nameController.dispose();
    _radiusController.dispose();
    _mapController.dispose();
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _getCurrentLocation() async {
    final permission = await Geolocator.requestPermission();
    if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
      return;
    }
    final pos = await Geolocator.getCurrentPosition();
    final latlng = LatLng(pos.latitude, pos.longitude);
    setState(() {
      _selectedPosition = latlng;
    });
    _mapController.move(latlng, 16);
  }

  void _onMapTap(TapPosition _, LatLng position) {
    setState(() {
      _selectedPosition = position;
    });
  }

  Future<void> _savePlace() async {
    if (_nameController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Digite um nome para o lugar')),
      );
      return;
    }
    if (_selectedPosition == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Selecione uma localização no mapa')),
      );
      return;
    }

    final radius = double.tryParse(_radiusController.text) ?? 100;
    await ref.read(geofenceManagerProvider).addPlace(
      name: _nameController.text.trim(),
      latitude: _selectedPosition!.latitude,
      longitude: _selectedPosition!.longitude,
      radiusMeters: radius,
    );

    setState(() {
      _nameController.clear();
      _radiusController.text = '100';
      _selectedPosition = null;
    });

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Lugar salvo com sucesso!')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: const Text('Meus Lugares'),
        backgroundColor: const Color(0xFF07090F),
        actions: [
          IconButton(
            icon: const Icon(Icons.my_location),
            onPressed: _getCurrentLocation,
            tooltip: 'Localização atual',
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: const Color(0xFF6366F1),
          labelColor: Colors.white,
          unselectedLabelColor: const Color(0xFF5E6A7E),
          tabs: const [
            Tab(text: 'Lugares'),
            Tab(text: 'Histórico'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _buildPlacesTab(),
          _buildHistoryTab(),
        ],
      ),
    );
  }

  Widget _buildPlacesTab() {
    return Column(
        children: [
          SizedBox(
            height: 300,
            child: Stack(
              children: [
                FlutterMap(
                  mapController: _mapController,
                  options: MapOptions(
                    initialCenter: const LatLng(-23.5505, -46.6333),
                    initialZoom: 12,
                    onTap: _onMapTap,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.sirius.sirius_companion',
                    ),
                    if (_selectedPosition != null) ...[
                      CircleLayer(circles: [
                        CircleMarker(
                          point: _selectedPosition!,
                          radius: double.tryParse(_radiusController.text) ?? 100,
                          useRadiusInMeter: true,
                          color: const Color(0xFF6366F1).withValues(alpha: 0.15),
                          borderColor: const Color(0xFF6366F1),
                          borderStrokeWidth: 2,
                        ),
                      ]),
                      MarkerLayer(markers: [
                        Marker(
                          point: _selectedPosition!,
                          child: const Icon(Icons.location_on, color: Color(0xFF6366F1), size: 36),
                        ),
                      ]),
                    ],
                  ],
                ),
                if (_selectedPosition == null)
                  const Center(
                    child: Text(
                      'Toque no mapa para selecionar um lugar\nOu use o botão de localização atual',
                      style: TextStyle(color: Colors.white70, fontSize: 14),
                      textAlign: TextAlign.center,
                    ),
                  ),
              ],
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  TextField(
                    controller: _nameController,
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      labelText: 'Nome do lugar',
                      labelStyle: const TextStyle(color: Color(0xFF9CA3AF)),
                      hintText: 'Ex: Casa, Trabalho, Academia',
                      hintStyle: const TextStyle(color: Color(0xFF5E6A7E)),
                      filled: true,
                      fillColor: const Color(0xFFFFFFFF).withValues(alpha: 0.05),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(color: const Color(0xFFFFFFFF).withValues(alpha: 0.1)),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: const BorderSide(color: Color(0xFF6366F1), width: 2),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _radiusController,
                          keyboardType: TextInputType.number,
                          style: const TextStyle(color: Colors.white),
                          decoration: InputDecoration(
                            labelText: 'Raio (metros)',
                            labelStyle: const TextStyle(color: Color(0xFF9CA3AF)),
                            filled: true,
                            fillColor: const Color(0xFFFFFFFF).withValues(alpha: 0.05),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                              borderSide: BorderSide(color: const Color(0xFFFFFFFF).withValues(alpha: 0.1)),
                            ),
                            focusedBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(12),
                              borderSide: const BorderSide(color: Color(0xFF6366F1), width: 2),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _savePlace,
                      icon: const Icon(Icons.save, size: 20),
                      label: const Text('SALVAR LUGAR'),
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF6366F1),
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        textStyle: const TextStyle(fontWeight: FontWeight.w700, letterSpacing: 1),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    'Lugares Salvos',
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Colors.white),
                  ),
                  const SizedBox(height: 8),
                  Consumer(
                    builder: (context, ref, _) {
                      final placesAsync = ref.watch(activeGeofencesProvider);
                      return placesAsync.when(
                        data: (places) {
                          if (places.isEmpty) {
                            return Container(
                              padding: const EdgeInsets.all(24),
                              decoration: BoxDecoration(
                                color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
                                border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
                                borderRadius: BorderRadius.circular(16),
                              ),
                              child: const Center(
                                child: Column(
                                  children: [
                                    Icon(Icons.place_outlined, size: 32, color: Color(0xFF5E6A7E)),
                                    SizedBox(height: 8),
                                    Text(
                                      'Nenhum lugar salvo',
                                      style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 14),
                                    ),
                                    SizedBox(height: 4),
                                    Text(
                                      'Toque no mapa e salve um lugar',
                                      style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 12),
                                    ),
                                  ],
                                ),
                              ),
                            );
                          }
                          return ListView.separated(
                            shrinkWrap: true,
                            physics: const NeverScrollableScrollPhysics(),
                            itemCount: places.length,
                            separatorBuilder: (_, __) => const SizedBox(height: 8),
                            itemBuilder: (context, index) {
                              final place = places[index];
                              return _PlaceTile(
                                place: place,
                                onTap: () => _centerOnPlace(places[index]),
                                onDelete: () => _confirmDelete(places[index]),
                                onToggle: (val) => ref.read(geofenceManagerProvider).updatePlace(
                                  places[index].copyWith(isActive: val),
                                ),
                              );
                            },
                          );
                        },
                        loading: () => const Center(child: CircularProgressIndicator(color: Color(0xFF6366F1))),
                        error: (e, _) => Center(
                          child: Text('Erro: $e', style: const TextStyle(color: Color(0xFFEF4444))),
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
          ),
        ],
    );
  }

  void _centerOnPlace(GeofenceRegion place) {
    _mapController.move(LatLng(place.latitude, place.longitude), 16);
  }

  Widget _buildHistoryTab() {
    return StreamBuilder<List<PlaceVisit>>(
      stream: _visitRepo.watchAll(),
      builder: (context, snapshot) {
        final visits = snapshot.data ?? [];
        if (visits.isEmpty) {
          return const Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.history, size: 48, color: Color(0xFF5E6A7E)),
                SizedBox(height: 12),
                Text(
                  'Nenhuma visita registrada',
                  style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 16),
                ),
                SizedBox(height: 4),
                Text(
                  'Visitas são registradas automaticamente',
                  style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 13),
                ),
              ],
            ),
          );
        }

        // Stats
        int totalVisits = visits.length;
        int totalSeconds = 0;
        int endedCount = 0;
        for (final v in visits) {
          if (v.durationSeconds > 0) {
            totalSeconds += v.durationSeconds;
            endedCount++;
          }
        }
        final totalDuration = Duration(seconds: totalSeconds);
        final avgMinutes = endedCount > 0 ? totalDuration.inMinutes / endedCount : 0.0;

        // Find most visited place.
        final placeCounts = <String, int>{};
        for (final v in visits) {
          placeCounts[v.placeName] = (placeCounts[v.placeName] ?? 0) + 1;
        }
        final mostVisited = placeCounts.isNotEmpty
            ? (placeCounts.entries.toList()..sort((a, b) => b.value.compareTo(a.value))).first.key
            : '-';

        return Column(
          children: [
            // Stats cards
            Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  _HistoryStatCard(
                    icon: Icons.people,
                    label: 'Total',
                    value: '$totalVisits',
                  ),
                  const SizedBox(width: 8),
                  _HistoryStatCard(
                    icon: Icons.timer,
                    label: 'Média',
                    value: '${avgMinutes.toStringAsFixed(0)}min',
                  ),
                  const SizedBox(width: 8),
                  _HistoryStatCard(
                    icon: Icons.place,
                    label: 'Mais visitado',
                    value: mostVisited,
                  ),
                ],
              ),
            ),
            // Visit list
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: visits.length,
                itemBuilder: (context, index) {
                  final visit = visits[index];
                  final duration = Duration(seconds: visit.durationSeconds);
                  final hours = duration.inHours;
                  final mins = duration.inMinutes.remainder(60);
                  final durationStr = hours > 0 ? '${hours}h ${mins}m' : '${mins}m';

                  final entered = '${visit.enteredAt.hour.toString().padLeft(2, '0')}:${visit.enteredAt.minute.toString().padLeft(2, '0')}';
                  final date = '${visit.enteredAt.day.toString().padLeft(2, '0')}/${visit.enteredAt.month.toString().padLeft(2, '0')}';
                  final hasEnded = visit.exitedAt != null;

                  return Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
                      border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 40,
                          height: 40,
                          decoration: BoxDecoration(
                            color: (hasEnded ? const Color(0xFF22C55E) : const Color(0xFFFBBF24)).withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Icon(
                            hasEnded ? Icons.check_circle : Icons.access_time,
                            color: hasEnded ? const Color(0xFF22C55E) : const Color(0xFFFBBF24),
                            size: 20,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                visit.placeName,
                                style: const TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: Colors.white,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                '$date • $entered${hasEnded ? ' → ${visit.exitedAt!.hour.toString().padLeft(2, '0')}:${visit.exitedAt!.minute.toString().padLeft(2, '0')}' : ''}',
                                style: const TextStyle(fontSize: 11, color: Color(0xFF5E6A7E)),
                              ),
                            ],
                          ),
                        ),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(
                              durationStr,
                              style: const TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                                color: Color(0xFF6366F1),
                              ),
                            ),
                            if (!hasEnded)
                              const Text(
                                'Em andamento',
                                style: TextStyle(fontSize: 10, color: Color(0xFFFBBF24)),
                              ),
                          ],
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        );
      },
    );
  }

  Future<void> _confirmDelete(GeofenceRegion place) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0D1117),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Excluir lugar?', style: TextStyle(color: Colors.white)),
        content: Text(
          'Remover "${place.name}"? Esta ação não pode ser desfeita.',
          style: const TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar', style: TextStyle(color: Color(0xFF9CA3AF))),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFFEF4444)),
            child: const Text('Excluir'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      await ref.read(geofenceManagerProvider).deletePlace(place.id);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Lugar excluído')),
        );
      }
    }
  }
}

class _PlaceTile extends StatelessWidget {
  final GeofenceRegion place;
  final VoidCallback onTap;
  final VoidCallback onDelete;
  final ValueChanged<bool> onToggle;

  const _PlaceTile({
    required this.place,
    required this.onTap,
    required this.onDelete,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
          border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: place.isActive
                    ? const Color(0xFF22C55E).withValues(alpha: 0.15)
                    : const Color(0xFF5E6A7E).withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(
                place.isActive ? Icons.location_on : Icons.location_off,
                color: place.isActive ? const Color(0xFF22C55E) : const Color(0xFF5E6A7E),
                size: 20,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    place.name,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: place.isActive ? Colors.white : const Color(0xFF9CA3AF),
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${place.radiusMeters.toInt()}m raio • ${place.latitude.toStringAsFixed(4)}, ${place.longitude.toStringAsFixed(4)}',
                    style: const TextStyle(fontSize: 11, color: Color(0xFF5E6A7E)),
                  ),
                ],
              ),
            ),
            Switch(
              value: place.isActive,
              onChanged: (val) => onToggle(val),
              activeColor: const Color(0xFF22C55E),
              inactiveThumbColor: const Color(0xFF5E6A7E),
              inactiveTrackColor: const Color(0xFF5E6A7E).withValues(alpha: 0.5),
            ),
            IconButton(
              icon: const Icon(Icons.delete_outline, color: Color(0xFFEF4444), size: 20),
              onPressed: onDelete,
              tooltip: 'Excluir',
            ),
          ],
        ),
      ),
    );
  }
}

class _HistoryStatCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _HistoryStatCard({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          children: [
            Icon(icon, size: 18, color: const Color(0xFF6366F1)),
            const SizedBox(height: 4),
            Text(
              value,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: const TextStyle(fontSize: 10, color: Color(0xFF5E6A7E)),
            ),
          ],
        ),
      ),
    );
  }
}
