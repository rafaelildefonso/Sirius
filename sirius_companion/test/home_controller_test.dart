import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/features/home/application/home_controller.dart';

void main() {
  test('clears sync progress and error when requested', () {
    final previous = HomeState(
      isSyncing: true,
      lastError: 'Conexão falhou',
      syncProgressMessage: 'Procurando PC na rede local...',
    );

    final finished = previous.copyWith(
      isSyncing: false,
      clearLastError: true,
      clearSyncProgressMessage: true,
    );

    expect(finished.isSyncing, isFalse);
    expect(finished.lastError, isNull);
    expect(finished.syncProgressMessage, isNull);
  });
}
