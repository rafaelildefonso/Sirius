class AppConstants {
  static const String appName = 'SIRIUS Companion';
  static const String packageName = 'com.sirius.companion';
  
  // API
  static const String defaultBaseUrl = 'http://192.168.1.3:8000';
  static const Duration apiTimeout = Duration(seconds: 30);
  static const Duration connectTimeout = Duration(seconds: 10);
  
  // Sync
  static const Duration syncInterval = Duration(minutes: 15);
  static const int maxBatchSize = 100;
  static const int maxRetries = 4;
  /// Items with more retries than this are dead-lettered: they stop being
  /// pushed on every sync cycle and only count towards the "Falhas" stat.
  static const int deadLetterRetries = 10;
  static const List<Duration> retryBackoff = [
    Duration(seconds: 30),
    Duration(minutes: 2),
    Duration(minutes: 10),
    Duration(hours: 1),
  ];
  
  // Location
  static const Duration locationUpdateInterval = Duration(seconds: 30);
  static const int locationDistanceFilter = 50; // meters
  static const Duration geofenceDwellDelay = Duration(minutes: 2);
  
  // Database
  static const String dbName = 'sirius_companion.sqlite';
  
  // Notifications
  static const String geofenceChannelId = 'geofence_channel';
  static const String geofenceChannelName = 'Geofence Alerts';
  static const String syncChannelId = 'sync_channel';
  static const String syncChannelName = 'Sync Status';
  static const String taskAlarmChannelId = 'task_alarm_channel';
  static const String taskAlarmChannelName = 'Lembretes de Tarefas';
  
  // Gemma
  static const String gemmaModelFileName = 'Gemma3-1B-IT_multi-prefill-seq_q4_block128_ekv1280.task';
  static const int gemmaMinRamGb = 3;
  static const String gemmaDownloadUrl = 'https://huggingface.co/litert-community/Gemma3-1B-IT/resolve/main/Gemma3-1B-IT_multi-prefill-seq_q4_block128_ekv1280.task';
  static const String gemmaHfRepoUrl = 'https://huggingface.co/google/gemma-3-1b-it';
  
  // Device Identity
  static const String deviceIdStorageKey = 'sirius_device_id';
  static const String deviceTokenStorageKey = 'sirius_device_token';
  static const String pairedDeviceIdKey = 'sirius_paired_device_id';
  static const String pairedAtKey = 'sirius_paired_at';
  
  // Headers
  static const String headerDeviceId = 'X-Device-ID';
  static const String headerDeviceToken = 'Authorization';
  static const String headerAppVersion = 'X-App-Version';
  static const String headerPlatform = 'X-Platform';
}

enum SyncItemType {
  command('command'),
  locationLog('location_log'),
  placeConfirmation('place_confirmation'),
  gemmaFallback('gemma_fallback'),
  quickTask('quick_task'),
  taskDone('task_done'),
  taskSnooze('task_snooze');
  
  const SyncItemType(this.value);
  final String value;
  
  static SyncItemType fromString(String value) {
    return SyncItemType.values.firstWhere(
      (e) => e.value == value,
      orElse: () => SyncItemType.command,
    );
  }
}

enum GeofenceEventType {
  enter('ENTER'),
  exit('EXIT'),
  dwell('DWELL');
  
  const GeofenceEventType(this.value);
  final String value;
  
  static GeofenceEventType fromString(String value) {
    return GeofenceEventType.values.firstWhere(
      (e) => e.value == value,
      orElse: () => GeofenceEventType.enter,
    );
  }
}

enum PairingStatus {
  unknown,
  pending,
  paired,
  rejected,
  error,
}