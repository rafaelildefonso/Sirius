import 'package:uuid/uuid.dart';

class Place {
  final int id;
  final String uuid;
  final String name;
  final double latitude;
  final double longitude;
  final double radiusMeters;
  final bool isActive;
  final DateTime createdAt;
  final DateTime? lastTriggeredAt;
  final int triggerCount;

  Place({
    required this.id,
    required this.uuid,
    required this.name,
    required this.latitude,
    required this.longitude,
    required this.radiusMeters,
    required this.isActive,
    required this.createdAt,
    this.lastTriggeredAt,
    this.triggerCount = 0,
  });

  factory Place.fromDrift({
    required int id,
    required String uuid,
    required String name,
    required double latitude,
    required double longitude,
    required double radiusMeters,
    required bool isActive,
    required DateTime createdAt,
    DateTime? lastTriggeredAt,
    int triggerCount = 0,
  }) {
    return Place(
      id: id,
      uuid: uuid,
      name: name,
      latitude: latitude,
      longitude: longitude,
      radiusMeters: radiusMeters,
      isActive: isActive,
      createdAt: createdAt,
      lastTriggeredAt: lastTriggeredAt,
      triggerCount: triggerCount,
    );
  }

  GeofenceRegion toGeofenceRegion() => GeofenceRegion(
    id: uuid,
    latitude: latitude,
    longitude: longitude,
    radiusMeters: radiusMeters,
  );

  Map<String, dynamic> toJson() => {
    'id': uuid,
    'name': name,
    'latitude': latitude,
    'longitude': longitude,
    'radius_meters': radiusMeters,
    'is_active': isActive,
    'created_at': createdAt.toIso8601String(),
    'last_triggered_at': lastTriggeredAt?.toIso8601String(),
    'trigger_count': triggerCount,
  };

  factory Place.fromJson(Map<String, dynamic> json) => Place(
    id: json['id'] as int? ?? 0,
    uuid: json['id'] as String? ?? json['uuid'] as String? ?? '',
    name: json['name'] as String? ?? '',
    latitude: (json['latitude'] as num? ?? 0.0).toDouble(),
    longitude: (json['longitude'] as num? ?? 0.0).toDouble(),
    radiusMeters: (json['radius_meters'] as num? ?? 100.0).toDouble(),
    isActive: json['is_active'] as bool? ?? true,
    createdAt: json['created_at'] != null 
        ? DateTime.parse(json['created_at'] as String) 
        : DateTime.now(),
    lastTriggeredAt: json['last_triggered_at'] != null 
        ? DateTime.parse(json['last_triggered_at'] as String) 
        : null,
    triggerCount: json['trigger_count'] as int? ?? 0,
  );

  factory Place.create({
    required String name,
    required double latitude,
    required double longitude,
    double radiusMeters = 100.0,
  }) {
    return Place(
      id: 0,
      uuid: Uuid().v4(),
      name: name,
      latitude: latitude,
      longitude: longitude,
      radiusMeters: radiusMeters,
      isActive: true,
      createdAt: DateTime.now(),
    );
  }
}

class GeofenceRegion {
  final String id;
  final double latitude;
  final double longitude;
  final double radiusMeters;

  GeofenceRegion({
    required this.id,
    required this.latitude,
    required this.longitude,
    required this.radiusMeters,
  });
}