import 'dart:convert';
import 'package:uuid/uuid.dart';
import '../../config/constants.dart';

class SyncItem {
  final int id;
  final String type;
  final String payloadJson;
  final DateTime createdAt;
  final DateTime? syncedAt;
  final int retryCount;
  final String? lastError;
  final String clientId;

  SyncItem({
    required this.id,
    required this.type,
    required this.payloadJson,
    required this.createdAt,
    this.syncedAt,
    this.retryCount = 0,
    this.lastError,
    required this.clientId,
  });

  SyncItemType get itemType => SyncItemType.fromString(type);

  Map<String, dynamic> get payload {
    try {
      return Map<String, dynamic>.from(jsonDecode(payloadJson));
    } catch (_) {
      return {'raw': payloadJson};
    }
  }

  Map<String, dynamic> toJson() => {
    'type': type,
    'payload': payload,
    'client_id': clientId,
  };

  static SyncItem createCommand({
    required String text,
    required DateTime timestamp,
    double? latitude,
    double? longitude,
    String? processedJson,
    String? placeId,
  }) {
    final clientId = Uuid().v4();
    return SyncItem(
      id: 0,
      type: SyncItemType.command.value,
      payloadJson: jsonEncode({
        'text': text,
        'timestamp': timestamp.toIso8601String(),
        'latitude': latitude,
        'longitude': longitude,
        'processed_json': processedJson,
        'place_id': placeId,
      }),
      createdAt: timestamp,
      clientId: clientId,
    );
  }

  static SyncItem createLocationLog({
    required double latitude,
    required double longitude,
    required double accuracy,
    required DateTime timestamp,
    String? placeId,
    String? placeName,
    required GeofenceEventType eventType,
  }) {
    final clientId = Uuid().v4();
    return SyncItem(
      id: 0,
      type: SyncItemType.locationLog.value,
      payloadJson: jsonEncode({
        'latitude': latitude,
        'longitude': longitude,
        'accuracy': accuracy,
        'timestamp': timestamp.toIso8601String(),
        'place_id': placeId,
        'place_name': placeName,
        'event_type': eventType.value,
      }),
      createdAt: timestamp,
      clientId: clientId,
    );
  }

  static SyncItem createPlaceConfirmation({
    required String placeId,
    required double latitude,
    required double longitude,
    required DateTime timestamp,
  }) {
    final clientId = Uuid().v4();
    return SyncItem(
      id: 0,
      type: SyncItemType.placeConfirmation.value,
      payloadJson: jsonEncode({
        'place_id': placeId,
        'latitude': latitude,
        'longitude': longitude,
        'timestamp': timestamp.toIso8601String(),
      }),
      createdAt: timestamp,
      clientId: clientId,
    );
  }
}