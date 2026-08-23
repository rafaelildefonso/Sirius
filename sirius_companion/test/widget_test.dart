import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sirius_companion/core/device_identity.dart';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sirius_companion/main.dart';

void main() {
  testWidgets('Pairing screen loads', (WidgetTester tester) async {
    DeviceIdentity.setTestPaired(false);
    await tester.pumpWidget(
        const ProviderScope(child: SiriusCompanionApp()),
      );
    await tester.pumpAndSettle();

    // Verify that the pairing screen loads
    expect(find.text('SIRIUS'), findsOneWidget);
    expect(find.text('Companion'), findsOneWidget);
    expect(find.text('Conectar ao SIRIUS'), findsOneWidget);
  });
}