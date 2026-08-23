// Background location isolate for geofencing
// Runs in a separate isolate to avoid blocking the main UI thread

import 'dart:async';
import 'dart:isolate';
import 'package:geolocator/geolocator.dart';
import '../application/geofence_manager.dart';

@pragma('vm:entry-point')
void locationIsolateEntry(SendPort mainPort) {
  final receivePort = ReceivePort();
  mainPort.send(receivePort.sendPort);

  final state = _GeofenceState();

  receivePort.listen((message) async {
    if (message is StartTracking) {
      state.updateGeofences(message.geofences);
      if (!state._isRunning) {
        await _startBackgroundTracking(state, mainPort);
      }
    }
  });
}

class _GeofenceState {
  List<GeofenceRegion> geofences = [];
  final Map<String, bool> _wasInside = {};
  final Map<String, DateTime> _enteredAt = {};
  bool _isRunning = false;

  void updateGeofences(List<GeofenceRegion> newGeofences) {
    geofences = newGeofences;
    // Remove stale entries
    _wasInside.removeWhere((key, _) => !geofences.any((g) => g.id == key));
    _enteredAt.removeWhere((key, _) => !geofences.any((g) => g.id == key));
  }

  bool isInside(String id) => _wasInside[id] ?? false;
  void setInside(String id, bool value) => _wasInside[id] = value;
  DateTime? enteredAt(String id) => _enteredAt[id];
  void setEnteredAt(String id, DateTime time) => _enteredAt[id] = time;
}

Future<void> _startBackgroundTracking(_GeofenceState state, SendPort mainPort) async {
  if (state._isRunning) return;
  state._isRunning = true;

  final settings = LocationSettings(
    accuracy: LocationAccuracy.high,
    distanceFilter: 50,
  );

  final stream = Geolocator.getPositionStream(locationSettings: settings);
  await for (final Position pos in stream) {
    final now = DateTime.now();

    for (final gf in state.geofences) {
      final dist = Geolocator.distanceBetween(
        pos.latitude,
        pos.longitude,
        gf.latitude,
        gf.longitude,
      );
      final wasInside = state.isInside(gf.id);
      final isInside = dist <= gf.radiusMeters;

      if (isInside && !wasInside) {
        // Transition: outside → inside (ENTER)
        state.setInside(gf.id, true);
        state.setEnteredAt(gf.id, now);
        mainPort.send(GeofenceTriggerEvent(
          placeId: gf.id,
          placeName: gf.name,
          eventType: GeofenceEventType.enter,
          location: pos,
        ));
      } else if (!isInside && wasInside) {
        // Transition: inside → outside (EXIT)
        state.setInside(gf.id, false);
        state.setEnteredAt(gf.id, now);
        mainPort.send(GeofenceTriggerEvent(
          placeId: gf.id,
          placeName: gf.name,
          eventType: GeofenceEventType.exit,
          location: pos,
        ));
      } else if (isInside && wasInside) {
        // Still inside — check dwell (2+ minutes)
        final entered = state.enteredAt(gf.id);
        if (entered != null && now.difference(entered) > const Duration(minutes: 2)) {
          // Reset to avoid repeated dwell events
          state.setEnteredAt(gf.id, now);
          mainPort.send(GeofenceTriggerEvent(
            placeId: gf.id,
            placeName: gf.name,
            eventType: GeofenceEventType.dwell,
            location: pos,
          ));
        }
      }
    }

    // Send raw location log periodically (every 5 min)
    if (now.difference(_lastRawLog) > const Duration(minutes: 5)) {
      mainPort.send(RawLocationLog(pos));
      _lastRawLog = now;
    }
  }

  state._isRunning = false;
}

DateTime _lastRawLog = DateTime.fromMillisecondsSinceEpoch(0);