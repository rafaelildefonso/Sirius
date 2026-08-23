package com.sirius.companion

import android.app.ActivityManager
import android.content.Context
import android.content.pm.PackageManager
import com.google.mediapipe.tasks.genai.llminference.LlmInference
import com.google.mediapipe.tasks.genai.llminference.LlmInferenceSession
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.MethodChannel.MethodCallHandler
import io.flutter.plugin.common.MethodChannel.Result
import android.webkit.CookieManager
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.pow

class GemmaModule : FlutterPlugin, ActivityAware, MethodCallHandler {

    private var channel: MethodChannel? = null
    private var context: Context? = null
    private var activity: android.app.Activity? = null
    private var llmInference: LlmInference? = null
    private var llmInferenceSession: LlmInferenceSession? = null
    private var isInitialized = false

    companion object {
        private const val CHANNEL = "sirius/gemma"
        private const val MODEL_FILENAME = "Gemma3-1B-IT_multi-prefill-seq_q4_block128_ekv1280.task"
        private const val MIN_RAM_GB = 3L
    }

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel = MethodChannel(binding.binaryMessenger, CHANNEL)
        channel?.setMethodCallHandler(this)
        context = binding.applicationContext
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel?.setMethodCallHandler(null)
        channel = null
        shutdown()
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivityForConfigChanges() {
        activity = null
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivity() {
        activity = null
    }

    override fun onMethodCall(call: MethodCall, result: Result) {
        when (call.method) {
            "checkHardware" -> {
                result.success(checkHardwareRequirements())
            }
            "checkModelExists" -> {
                result.success(checkModelExists())
            }
            "downloadWithCookies" -> {
                val cookies = call.argument<String>("cookies") ?: ""
                val token = call.argument<String>("token") ?: ""
                val downloadUrl = call.argument<String>("url") ?: "https://huggingface.co/litert-community/Gemma3-1B-IT/resolve/main/${MODEL_FILENAME}"
                downloadModel(cookies, token, downloadUrl) { success, error ->
                    if (success) {
                        result.success(true)
                    } else {
                        result.error("DOWNLOAD_FAILED", error ?: "Failed to download model", null)
                    }
                }
            }
            "initialize" -> {
                initializeModel { success, error ->
                    if (success) {
                        result.success(true)
                    } else {
                        result.error("INIT_FAILED", error ?: "Failed to initialize Gemma", null)
                    }
                }
            }
            "generate" -> {
                val prompt = call.argument<String>("prompt") ?: ""
                generateResponse(prompt) { response, error ->
                    if (error != null) {
                        result.error("GENERATE_FAILED", error, null)
                    } else {
                        result.success(response)
                    }
                }
            }
            "shutdown" -> {
                shutdown()
                result.success(true)
            }
            else -> result.notImplemented()
        }
    }

    private fun checkHardwareRequirements(): Boolean {
        context?.let { ctx ->
            val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            val memInfo = ActivityManager.MemoryInfo()
            am.getMemoryInfo(memInfo)
            val availableGB = memInfo.availMem / (1024 * 1024 * 1024)

            val hasVulkan = ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_VERSION) ||
                    ctx.packageManager.hasSystemFeature("android.hardware.vulkan.compute")

            return availableGB >= MIN_RAM_GB && hasVulkan
        }
        return false
    }

    private fun checkModelExists(): Boolean {
        if (context == null) return false
        val modelFile = File(context!!.filesDir, MODEL_FILENAME)
        return modelFile.exists()
    }

    private fun getHfCookies(): String {
        return try {
            CookieManager.getInstance().getCookie("https://huggingface.co") ?: ""
        } catch (e: Exception) {
            ""
        }
    }

    private fun downloadModel(cookies: String, token: String, downloadUrl: String, callback: (Boolean, String?) -> Unit) {
        CoroutineScope(Dispatchers.IO).launch {
            val maxAttempts = 3
            var attempt = 0
            var success = false
            var lastError: String? = null

            while (attempt < maxAttempts && !success) {
                attempt++
                try {
                    val modelFile = File(context!!.filesDir, MODEL_FILENAME)

                    val url = URL(downloadUrl)
                    val connection = url.openConnection() as HttpURLConnection
                    if (token.isNotEmpty()) {
                        connection.setRequestProperty("Authorization", "Bearer $token")
                    }
                    // Get cookies from Android CookieManager (has HttpOnly hf-session) or fall back
                    val hfCookies = getHfCookies()
                    val allCookies = if (hfCookies.isNotEmpty()) hfCookies else cookies
                    if (allCookies.isNotEmpty()) {
                        connection.setRequestProperty("Cookie", allCookies)
                    }
                    connection.setRequestProperty("User-Agent", "SIRIUS-Companion/1.0")
                    connection.connectTimeout = 30000
                    connection.readTimeout = 60000
                    connection.connect()

                    val responseCode = connection.responseCode
                    if (responseCode != HttpURLConnection.HTTP_OK) {
                        lastError = "Server returned HTTP $responseCode (${connection.responseMessage})"
                        connection.disconnect()
                        continue
                    }

                    val fileLength = connection.contentLengthLong
                    val input: InputStream = connection.inputStream
                    val output = FileOutputStream(modelFile)

                    val buffer = ByteArray(8192)
                    var total = 0L
                    var len: Int

                    while (input.read(buffer).also { len = it } != -1) {
                        output.write(buffer, 0, len)
                        total += len
                        if (fileLength > 0) {
                            val progress = total.toDouble() / fileLength
                            CoroutineScope(Dispatchers.Main).launch {
                                channel?.invokeMethod("downloadProgress", mapOf("progress" to progress))
                            }
                        }
                    }

                    output.flush()
                    output.close()
                    input.close()
                    connection.disconnect()

                    if (modelFile.exists() && modelFile.length() > 0) {
                        success = true
                        callback(true, null)
                    } else {
                        lastError = "Downloaded file is empty"
                    }
                } catch (e: Exception) {
                    e.printStackTrace()
                    lastError = e.message ?: "Download failed"
                }
                if (!success && attempt < maxAttempts) {
                    // exponential backoff before next attempt
                    delay((2.0.pow(attempt - 1) * 1000).toLong())
                }
            }
            if (!success) {
                callback(false, lastError ?: "Download failed after $maxAttempts attempts")
            }
        }
    }

    private fun initializeModel(callback: (Boolean, String?) -> Unit) {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val modelFile = File(context!!.filesDir, MODEL_FILENAME)
                if (!modelFile.exists()) {
                    callback(false, "Model file not found. Please download first.")
                    return@launch
                }

                val options = LlmInference.LlmInferenceOptions.builder()
                    .setModelPath(modelFile.absolutePath)
                    .setMaxTokens(1000)
                    .build()

                llmInference = LlmInference.createFromOptions(context!!, options)

                val sessionOptions = LlmInferenceSession.LlmInferenceSessionOptions.builder()
                    .setTopK(40)
                    .setTopP(0.95f)
                    .setTemperature(0.7f)
                    .build()

                llmInferenceSession = LlmInferenceSession.createFromOptions(llmInference!!, sessionOptions)
                isInitialized = true

                callback(true, null)
            } catch (e: Exception) {
                e.printStackTrace()
                callback(false, e.message ?: "Failed to initialize model")
            }
        }
    }

    private fun generateResponse(prompt: String, callback: (String?, String?) -> Unit) {
        if (!isInitialized || llmInferenceSession == null) {
            callback(null, "Model not initialized")
            return
        }

        CoroutineScope(Dispatchers.IO).launch {
            try {
                llmInferenceSession!!.addQueryChunk(prompt)
                val response = llmInferenceSession!!.generateResponse()
                callback(response, null)
            } catch (e: Exception) {
                callback(null, e.message ?: "Generation failed")
            }
        }
    }

    private fun shutdown() {
        try {
            llmInferenceSession?.close()
        } catch (_: Exception) {}
        try {
            llmInference?.close()
        } catch (_: Exception) {}
        llmInferenceSession = null
        llmInference = null
        isInitialized = false
    }
}
