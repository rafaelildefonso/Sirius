package com.sirius.sirius_companion

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import com.sirius.companion.GemmaModule
import android.app.NotificationManager
import android.app.AlarmManager
import android.os.Build
import android.os.Bundle
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.speech.tts.TextToSpeech
import java.util.Locale
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var reminderTts: TextToSpeech? = null
    private var ttsReady = false
    private val pendingSpeeches = mutableListOf<String>()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        flutterEngine.plugins.add(GemmaModule())
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "sirius/simulated_call")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "isDoNotDisturbActive" -> {
                        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                        result.success(!manager.isNotificationPolicyAccessGranted ||
                            manager.currentInterruptionFilter != NotificationManager.INTERRUPTION_FILTER_ALL)
                    }
                    "getAlertCapabilities" -> {
                        val notifications = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                        val alarms = getSystemService(Context.ALARM_SERVICE) as AlarmManager
                        result.success(mapOf(
                            "notifications" to notifications.areNotificationsEnabled(),
                            "fullScreen" to (Build.VERSION.SDK_INT < 34 || notifications.canUseFullScreenIntent()),
                            "exactAlarm" to (Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms()),
                            "dndAccess" to notifications.isNotificationPolicyAccessGranted
                        ))
                    }
                    "openDoNotDisturbAccessSettings" -> {
                        startActivity(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
                        result.success(null)
                    }
                    "speakReminder" -> {
                        val text = call.argument<String>("text")
                        if (text.isNullOrBlank()) {
                            result.error("TTS_INVALID_TEXT", "O lembrete está vazio", null)
                        } else if (!ttsReady) {
                            pendingSpeeches.add(text)
                            result.success(null)
                        } else {
                            speak(text, result)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
        reminderTts = TextToSpeech(this) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (ttsReady) {
                reminderTts?.setLanguage(Locale("pt", "BR"))
                pendingSpeeches.toList().forEach { text -> speak(text) }
                pendingSpeeches.clear()
            } else {
                android.util.Log.e("SiriusCall", "Android TextToSpeech initialization failed")
                pendingSpeeches.clear()
            }
        }
    }

    private fun speak(text: String, result: MethodChannel.Result? = null) {
        val status = reminderTts?.speak(
            text,
            TextToSpeech.QUEUE_FLUSH,
            Bundle(),
            "sirius-task-reminder",
        )
        if (status == TextToSpeech.ERROR || status == null) {
            if (result != null) {
                result.error("TTS_FAILED", "Speech failed", null)
            } else {
                android.util.Log.e("SiriusCall", "TextToSpeech failed")
            }
        } else {
            result?.success(null)
        }
    }

    override fun onDestroy() {
        reminderTts?.stop()
        reminderTts?.shutdown()
        reminderTts = null
        pendingSpeeches.clear()
        super.onDestroy()
    }
}
