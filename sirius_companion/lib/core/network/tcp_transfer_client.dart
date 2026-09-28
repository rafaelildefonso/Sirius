import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

class TcpTransferProgress {
  final int itemIndex;
  final int totalItems;
  final int bytesSent;
  final int totalBytes;
  final double speedBps;

  TcpTransferProgress({
    required this.itemIndex,
    required this.totalItems,
    required this.bytesSent,
    required this.totalBytes,
    required this.speedBps,
  });
}

class TcpTransferItem {
  final String uuid;
  final String type;
  final String category;
  final String title;
  final String content;
  final String? aiSummary;
  final List<String>? aiTags;
  final List<AttachmentData> attachments;
  final int contentLength;

  TcpTransferItem({
    required this.uuid,
    required this.type,
    required this.category,
    required this.title,
    required this.content,
    this.aiSummary,
    this.aiTags,
    this.attachments = const [],
    required this.contentLength,
  });
}

class AttachmentData {
  final String name;
  final Uint8List bytes;

  AttachmentData({required this.name, required this.bytes});
}

class TcpItemResult {
  final String uuid;
  final bool ok;
  final String? error;
  final Map<String, dynamic> data;

  TcpItemResult({
    required this.uuid,
    required this.ok,
    this.error,
    this.data = const {},
  });
}

class TcpTransferClient {
  Socket? _socket;
  bool _connected = false;

  bool get isConnected => _connected;

  Future<void> connect(
    String host,
    int port, {
    Duration timeout = const Duration(seconds: 10),
  }) async {
    _socket = await Socket.connect(host, port, timeout: timeout);
    _connected = true;
  }

  Future<void> disconnect() async {
    try {
      await _socket?.flush();
      await _socket?.close();
    } catch (_) {}
    _socket = null;
    _connected = false;
  }

  /// Sends the session header. Must be called before sending items.
  Future<void> sendHeader({
    required String sessionKey,
    required String deviceId,
    required int totalItems,
    required int totalBytes,
  }) async {
    final header = jsonEncode({
      'version': 1,
      'session_key': sessionKey,
      'device_id': deviceId,
      'total_items': totalItems,
      'total_bytes': totalBytes,
    });
    _socket!.write('$header\n');
    await _socket!.flush();
  }

  /// Sends a single note item and waits for ACK.
  Future<TcpItemResult> sendNote(
    TcpTransferItem item, {
    void Function(TcpTransferProgress)? onProgress,
    int itemIndex = 0,
    int totalItems = 1,
  }) async {
    // Calculate total bytes for this item (JSON header + attachments).
    final itemHeader = _buildItemHeader(item);
    final headerBytes = utf8.encode('$itemHeader\n');
    int attachmentBytes = 0;
    for (final a in item.attachments) {
      attachmentBytes += a.bytes.length;
    }
    final itemTotalBytes = headerBytes.length + attachmentBytes;

    // Send item header.
    _socket!.write('$itemHeader\n');
    await _socket!.flush();

    // Send attachments with progress tracking.
    int bytesSent = headerBytes.length;
    final stopwatch = Stopwatch()..start();

    for (final attachment in item.attachments) {
      _socket!.add(attachment.bytes);
      bytesSent += attachment.bytes.length;
      await _socket!.flush();

      onProgress?.call(
        TcpTransferProgress(
          itemIndex: itemIndex,
          totalItems: totalItems,
          bytesSent: bytesSent,
          totalBytes: itemTotalBytes,
          speedBps: stopwatch.elapsedMilliseconds > 0
              ? (bytesSent * 1000) / stopwatch.elapsedMilliseconds
              : 0,
        ),
      );
    }

    // Wait for ACK from server.
    final ack = await _socket!
        .timeout(const Duration(seconds: 30))
        .map((data) => utf8.decode(data))
        .first
        .catchError((_) => '{}');

    try {
      final ackJson = jsonDecode(ack.trim()) as Map<String, dynamic>;
      return TcpItemResult(
        uuid: ackJson['uuid'] as String? ?? item.uuid,
        ok: ackJson['ok'] as bool? ?? false,
        error: ackJson['error'] as String?,
        data: (ackJson['result'] as Map?)?.cast<String, dynamic>() ?? const {},
      );
    } catch (_) {
      return TcpItemResult(uuid: item.uuid, ok: false, error: 'Invalid ACK');
    }
  }

  String _buildItemHeader(TcpTransferItem item) {
    return jsonEncode({
      'uuid': item.uuid,
      'type': item.type,
      'category': item.category,
      'title': item.title,
      'content': item.content,
      'ai_summary': item.aiSummary,
      'ai_tags': item.aiTags,
      'attachments': item.attachments
          .map((a) => {'name': a.name, 'size': a.bytes.length})
          .toList(),
      'content_length': item.contentLength,
    });
  }
}
