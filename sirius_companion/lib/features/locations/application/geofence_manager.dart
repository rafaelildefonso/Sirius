import 'dart:async';
import 'dart:convert';
import 'dart:isolate';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:geolocator/geolocator.dart';
import 'package:uuid/uuid.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:drift/drift.dart';
import '../background/location_isolate.dart';
import '../../../../core/storage/database/database.dart';
import '../../../../core/storage/repositories/sync_repository.dart';
import '../../../../core/storage/repositories/place_visit_repository.dart';
import '../../../../core/sync/sync_worker.dart';
import '../../../../core/sync/background_health_monitor.dart';

final geofenceManagerProvider = Provider<GeofenceManager>((ref) => GeofenceManager());

class GeofenceRegion {
  final String id;
  final String name;
  final double latitude;
  final double longitude;
  final double radiusMeters;
  final bool isActive;

  GeofenceRegion({
    required this.id,
    required this.name,
    required this.latitude,
    required this.longitude,
    required this.radiusMeters,
    required this.isActive,
  });

  GeofenceRegion copyWith({
    String? id,
    String? name,
    double? latitude,
    double? longitude,
    double? radiusMeters,
    bool? isActive,
  }) {
    return GeofenceRegion(
      id: id ?? this.id,
      name: name ?? this.name,
      latitude: latitude ?? this.latitude,
      longitude: longitude ?? this.longitude,
      radiusMeters: radiusMeters ?? this.radiusMeters,
      isActive: isActive ?? this.isActive,
    );
  }

  factory GeofenceRegion.fromPlace(Place place) {
    return GeofenceRegion(
      id: place.uuid,
      name: place.name,
      latitude: place.latitude,
      longitude: place.longitude,
      radiusMeters: place.radiusMeters,
      isActive: place.isActive,
    );
  }
}

enum GeofenceEventType { enter, exit, dwell }

class GeofenceTriggerEvent {
  final String placeId;
  final String placeName;
  final GeofenceEventType eventType;
  final Position location;

  GeofenceTriggerEvent({
    required this.placeId,
    required this.placeName,
    required this.eventType,
    required this.location,
  });
}

class StartTracking {
  final List<GeofenceRegion> geofences;
  StartTracking(this.geofences);
}

class GeofenceManager {
  static const String _geofenceChannelId = 'geofence_channel';

  final _backgroundService = FlutterBackgroundService();
  SendPort? _isolatePort;
  StreamSubscription? _isolateSubscription;
  final StreamController<GeofenceTriggerEvent> _triggerController = StreamController.broadcast();
  final _notifications = FlutterLocalNotificationsPlugin();

  /// Tracks active (un-ended) visit UUIDs per place.
  final Map<String, String> _activeVisitUuids = {};

  Stream<GeofenceTriggerEvent> get triggerStream => _triggerController.stream;

  Future<void> initialize() async {
    try {
      final granted = await _requestLocationPermissions();
      if (!granted) return;
      await _setupBackgroundService();
      await _startBackgroundIsolate();
      await _setupNotificationChannels();
    } catch (e) {
      print('[GeofenceManager] Init failed: $e');
    }
  }

  Future<bool> _requestLocationPermissions() async {
    final status = await Permission.location.request();
    if (status.isGranted) return true;
    if (status.isPermanentlyDenied) {
      final foreground = await Permission.locationWhenInUse.request();
      return foreground.isGranted;
    }
    return false;
  }

  Future<void> _setupBackgroundService() async {
    try {
      await _backgroundService.configure(
        iosConfiguration: IosConfiguration(),
        androidConfiguration: AndroidConfiguration(
          onStart: onStart,
          autoStart: true,
          isForegroundMode: true,
          foregroundServiceTypes: [
            AndroidForegroundType.location,
            AndroidForegroundType.dataSync,
          ],
          notificationChannelId: _geofenceChannelId,
          initialNotificationTitle: 'SIRIUS Companion',
          initialNotificationContent: 'Ativo',
          foregroundServiceNotificationId: 888,
        ),
      );
    } catch (e) {
      print('[GeofenceManager] Background service config failed: $e');
    }
  }

  Future<void> _startBackgroundIsolate() async {
    final receivePort = ReceivePort();
    await Isolate.spawn(locationIsolateEntry, receivePort.sendPort);

    _isolateSubscription = receivePort.listen((message) {
      if (message is SendPort) {
        _isolatePort = message;
        _syncGeofencesToIsolate();
        return;
      }
      if (message is GeofenceTriggerEvent) {
        _triggerController.add(message);
        _showLocalNotification(message);
        _notifyTrigger(message);
      }
    });
  }

  Future<void> _syncGeofencesToIsolate() async {
    final db = AppDatabase();
    final places = await (db.select(db.places)
          ..where((tbl) => tbl.isActive.equals(true)))
        .get();

    final geofences = places.map((p) => GeofenceRegion.fromPlace(p)).toList();
    _isolatePort?.send(StartTracking(geofences));
  }

  Future<void> _setupNotificationChannels() async {
    const androidDetails = AndroidNotificationChannel(
      'geofence_channel',
      'Geofence Alerts',
      description: 'Notificações ao entrar/sair de lugares salvos',
      importance: Importance.high,
    );
    await _notifications.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>()?.createNotificationChannel(androidDetails);
  }

  Future<void> _showLocalNotification(GeofenceTriggerEvent event) async {
    const androidDetails = AndroidNotificationDetails(
      'geofence_channel',
      'Geofence Alerts',
      channelDescription: 'Notificações ao entrar/sair de lugares salvos',
      icon: 'ic_stat_face',
      importance: Importance.high,
      priority: Priority.high,
      actions: [
        AndroidNotificationAction('confirm', 'Confirmar: Estou aqui'),
        AndroidNotificationAction('dismiss', 'Ignorar'),
      ],
      visibility: NotificationVisibility.public,
    );

    await _notifications.show(
      id: event.placeId.hashCode,
      title: '📍 ${event.placeName}',
      body: event.eventType == GeofenceEventType.enter
          ? 'Você entrou em "${event.placeName}". Confirmar presença?'
          : 'Você saiu de "${event.placeName}"',
      notificationDetails: const NotificationDetails(android: androidDetails),
      payload: '${event.placeId}|${event.eventType.name}',
    );
  }

  Future<void> _notifyTrigger(GeofenceTriggerEvent event) async {
    // Save to local DB for sync
    final syncRepo = SyncRepository(AppDatabase());
    await syncRepo.enqueue(
      type: 'place_confirmation',
      payloadJson: jsonEncode({
        'place_id': event.placeId,
        'event_type': event.eventType.name,
        'latitude': event.location.latitude,
        'longitude': event.location.longitude,
        'timestamp': DateTime.now().toIso8601String(),
      }),
      clientId: const Uuid().v4(),
    );
  }

  Future<void> addPlace({
    required String name,
    required double latitude,
    required double longitude,
    double radiusMeters = 100,
  }) async {
    final db = AppDatabase();
    await db.into(db.places).insert(
      PlacesCompanion.insert(
        uuid: const Uuid().v4(),
        name: name,
        latitude: latitude,
        longitude: longitude,
        createdAt: DateTime.now(),
      ),
    );
    await _syncGeofencesToIsolate();
  }

  Future<void> updatePlace(GeofenceRegion place) async {
    final db = AppDatabase();
    await (db.update(db.places)..where((tbl) => tbl.uuid.equals(place.id))).write(
      PlacesCompanion(
        name: Value(place.name),
        latitude: Value(place.latitude),
        longitude: Value(place.longitude),
        radiusMeters: Value(place.radiusMeters),
        isActive: Value(place.isActive),
      ),
    );
    await _syncGeofencesToIsolate();
  }

  Future<void> confirmPlace(String placeId, String eventType) async {
    final db = AppDatabase();
    final existing = await (db.select(db.places)
          ..where((tbl) => tbl.uuid.equals(placeId)))
        .getSingleOrNull();
    if (existing != null) {
      await (db.update(db.places)..where((tbl) => tbl.uuid.equals(placeId))).write(
        PlacesCompanion(
          lastTriggeredAt: Value(DateTime.now()),
          triggerCount: Value(existing.triggerCount + 1),
        ),
      );
    }

    // Track visit start/end.
    if (eventType == GeofenceEventType.enter.name) {
      await _startVisit(placeId, existing?.name ?? placeId);
    } else if (eventType == GeofenceEventType.exit.name) {
      await _endVisit(placeId, existing?.name ?? placeId);
    }

    await _notifyTriggerFromPlace(placeId, eventType);
  }

  Future<void> _startVisit(String placeId, String placeName) async {
    // Don't start a new visit if one is already active for this place.
    if (_activeVisitUuids.containsKey(placeId)) return;

    final visitRepo = PlaceVisitRepository(AppDatabase());
    final now = DateTime.now();
    final visitId = await visitRepo.startVisit(
      placeId: placeId,
      placeName: placeName,
      enteredAt: now,
      confirmed: true,
    );

    // Store the visit UUID for tracking.
    final visit = await AppDatabase().customSelect(
      'SELECT uuid FROM place_visits WHERE id = ?',
      variables: [Variable.withInt(visitId)],
    ).getSingleOrNull();
    if (visit != null) {
      _activeVisitUuids[placeId] = visit.data['uuid'] as String;
    }
  }

  Future<void> _endVisit(String placeId, String placeName) async {
    final visitUuid = _activeVisitUuids.remove(placeId);
    if (visitUuid == null) return;

    final visitRepo = PlaceVisitRepository(AppDatabase());
    final now = DateTime.now();
    await visitRepo.endVisitByUuid(uuid: visitUuid, exitedAt: now);

    // Fetch the visit to get duration.
    final db = AppDatabase();
    final visit = await (db.select(db.placeVisits)
          ..where((tbl) => tbl.uuid.equals(visitUuid)))
        .getSingleOrNull();

    if (visit != null) {
      final duration = Duration(seconds: visit.durationSeconds);
      final hours = duration.inHours;
      final minutes = duration.inMinutes.remainder(60);
      final durationStr = hours > 0 ? '${hours}h ${minutes}m' : '${minutes}m';

      // Show exit notification with duration.
      await _showExitNotification(placeName, durationStr);
    }
  }

  Future<void> _showExitNotification(String placeName, String duration) async {
    const androidDetails = AndroidNotificationDetails(
      'geofence_channel',
      'Geofence Alerts',
      channelDescription: 'Notificações ao entrar/sair de lugares salvos',
      icon: 'ic_stat_face',
      importance: Importance.high,
      priority: Priority.high,
      visibility: NotificationVisibility.public,
    );

    await _notifications.show(
      id: 'exit_$placeName'.hashCode.abs() % 2147483647,
      title: '👋 Saiu de $placeName',
      body: 'Tempo de permanência: $duration',
      notificationDetails: const NotificationDetails(android: androidDetails),
    );
  }

  Future<void> _notifyTriggerFromPlace(String placeId, String eventType) async {
    final syncRepo = SyncRepository(AppDatabase());
    final now = DateTime.now();
    await syncRepo.enqueue(
      type: 'place_confirmation',
      payloadJson: jsonEncode({
        'place_id': placeId,
        'event_type': eventType,
        'timestamp': now.toIso8601String(),
      }),
      clientId: const Uuid().v4(),
    );
  }

  Future<void> deletePlace(String placeId) async {
    final db = AppDatabase();
    await (db.delete(db.places)..where((tbl) => tbl.uuid.equals(placeId))).go();
    await _syncGeofencesToIsolate();
  }

  Future<List<GeofenceRegion>> getActiveGeofences() async {
    final db = AppDatabase();
    final places = await (db.select(db.places)
          ..where((tbl) => tbl.isActive.equals(true)))
        .get();
    return places.map((p) => GeofenceRegion.fromPlace(p)).toList();
  }

  void dispose() {
    _isolateSubscription?.cancel();
  }
}

// Background service entry point
@pragma('vm:entry-point')
void onStart(ServiceInstance service) async {
  if (service is AndroidServiceInstance) {
    service.setForegroundNotificationInfo(
      title: 'SIRIUS Companion',
      content: 'Ativo',
    );

    service.on('setAsForeground').listen((event) {
      service.setAsForegroundService();
    });
    service.on('setAsBackground').listen((event) {
      service.setAsBackgroundService();
    });

    // Self-healing: re-schedule if the OS kills the service.
    service.on('onTaskRemoved').listen((event) async {
      print('[BG Service] onTaskRemoved — scheduling restart');
      await BackgroundHealthMonitor.markStopped();
      // Give the OS a moment, then request restart via the global service.
      await Future.delayed(const Duration(seconds: 3));
      try {
        await FlutterBackgroundService().startService();
      } catch (_) {}
    });
  }

  service.on('stopService').listen((event) async {
    await BackgroundHealthMonitor.markStopped();
    service.stopSelf();
  });

  // Start heartbeat so the health monitor knows we're alive.
  BackgroundHealthMonitor.startHeartbeat();

  // Watchdog: if the service is still running after 5 min, restart it
  // to avoid zombie state where the foreground notification lingers but
  // timers are dead.
  Timer.periodic(const Duration(minutes: 5), (_) async {
    try {
      final isRunning = await FlutterBackgroundService().isRunning();
      if (!isRunning) {
        print('[BG Service] Watchdog detected service is not running — restarting');
        await FlutterBackgroundService().startService();
      }
    } catch (_) {}
  });

  // Periodic sync — silent, no notification update.
  Timer.periodic(const Duration(seconds: 60), (_) async {
    try {
      await SyncWorker.performSync();
    } catch (_) {}
  });

  // Immediate first sync
  await SyncWorker.performSync();
}

// Riverpod providers for reactive UI
final activeGeofencesProvider = StreamProvider<List<GeofenceRegion>>((ref) {
  final manager = ref.read(geofenceManagerProvider);
  return Stream.periodic(const Duration(seconds: 10), (_) => null)
      .asyncMap((_) => manager.getActiveGeofences());
});

final geofenceTriggerStreamProvider = StreamProvider<GeofenceTriggerEvent>((ref) {
  final manager = ref.read(geofenceManagerProvider);
  return manager.triggerStream;
});