package com.sirius.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Re-starts the foreground background-service after device reboot or app update.
 * The manifest declares this receiver for BOOT_COMPLETED, MY_PACKAGE_REPLACED,
 * and QUICKBOOT_POWERON.
 *
 * NOTE: We intentionally do NOT call GeneratedPluginRegistrant or create a
 * FlutterEngine here — the flutter_background_service plugin's own BootReceiver
 * handles the actual service restart when autoStart is true. Creating a
 * FlutterEngine in the BOOT_COMPLETED context caused RemoteServiceException
 * crashes because Android's 5-second startForeground() deadline expires before
 * the engine is fully initialized.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action
        if (action != Intent.ACTION_BOOT_COMPLETED &&
            action != Intent.ACTION_MY_PACKAGE_REPLACED &&
            action != "android.intent.action.QUICKBOOT_POWERON") {
            return
        }

        // The flutter_background_service plugin's own BootReceiver handles
        // the actual service restart when autoStart is true. No extra work needed.
    }
}
