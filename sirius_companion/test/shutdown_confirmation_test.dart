import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/features/home/presentation/shutdown_confirmation.dart';

void main() {
  testWidgets('computer shutdown requires an explicit confirmation', (
    tester,
  ) async {
    var requestSent = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                if (await confirmComputerShutdown(context)) requestSent = true;
              },
              child: const Text('Desligar computador'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Desligar computador'));
    await tester.pumpAndSettle();
    expect(requestSent, isFalse);
    expect(
      find.text('O computador pareado será desligado. Deseja continuar?'),
      findsOneWidget,
    );

    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(requestSent, isFalse);
  });

  testWidgets('only the confirmation button authorizes sending the request', (
    tester,
  ) async {
    var requestSent = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                if (await confirmComputerShutdown(context)) requestSent = true;
              },
              child: const Text('Open'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    expect(requestSent, isFalse);
    await tester.tap(find.text('Desligar computador'));
    await tester.pumpAndSettle();
    expect(requestSent, isTrue);
  });
}
