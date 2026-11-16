import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sirius_companion/features/pairing/presentation/pairing_screen.dart';

void main() {
  testWidgets('Pairing screen loads', (WidgetTester tester) async {
    await tester.pumpWidget(
      const ProviderScope(child: MaterialApp(home: PairingScreen())),
    );
    await tester.pumpAndSettle();

    // Verify that the pairing screen loads
    expect(find.text('SIRIUS'), findsOneWidget);
    expect(find.text('Companion'), findsOneWidget);
    expect(find.text('Conectar ao SIRIUS'), findsOneWidget);
  });
}
