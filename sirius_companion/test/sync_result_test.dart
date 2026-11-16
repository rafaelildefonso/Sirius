import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/core/network/api_client.dart';

void main() {
  test(
    'uses aggregate ACK from older PC when the whole batch was processed',
    () {
      final result = SyncResult.success(processed: 2);

      expect(result.confirmedClientIds(['first', 'second']), [
        'first',
        'second',
      ]);
    },
  );

  test('does not infer item ACKs from a partial aggregate count', () {
    final result = SyncResult.success(processed: 1);

    expect(result.confirmedClientIds(['first', 'second']), isEmpty);
  });

  test('matches per-item ACKs to submitted IDs', () {
    final result = SyncResult.success(
      processed: 1,
      results: [
        SyncItemResult(clientId: 'first', status: 'processed'),
        SyncItemResult(clientId: 'foreign', status: 'processed'),
      ],
    );

    expect(result.confirmedClientIds(['first', 'second']), ['first']);
  });
}
