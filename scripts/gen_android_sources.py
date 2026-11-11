#!/usr/bin/env python3
"""Write the Android app source files for Nova.

Kept as a script so the many small resource/source files can be regenerated
deterministically, which is handy in a container without an editor.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "android"

FILES: dict[str, str] = {}

# ---------------------------------------------------------------- resources
FILES["app/src/main/res/drawable/ic_launcher_foreground.xml"] = """\
<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFFFFF"
        android:pathData="M54,26 C56,40 62,46 76,48 C62,50 56,56 54,70 C52,56 46,50 32,48 C46,46 52,40 54,26 Z" />
    <path android:fillColor="#B9C7FF"
        android:pathData="M76,62 C77,69 80,72 87,73 C80,74 77,77 76,84 C75,77 72,74 65,73 C72,72 75,69 76,62 Z" />
</vector>
"""

FILES["app/src/main/res/drawable/ic_launcher_background.xml"] = """\
<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#141B2D" android:pathData="M0,0h108v108h-108z" />
</vector>
"""

FILES["app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml"] = """\
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
</adaptive-icon>
"""

FILES["app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml"] = FILES[
    "app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml"
]

# ------------------------------------------------------------------- Kotlin
FILES["app/src/main/java/ai/nova/assistant/Prefs.kt"] = """\
package ai.nova.assistant

import android.content.Context
import android.content.SharedPreferences

/** Small wrapper around SharedPreferences for the server settings. */
class Prefs(context: Context) {
    private val sp: SharedPreferences =
        context.getSharedPreferences("nova", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server_url", "http://10.0.2.2:8000") ?: ""
        set(v) = sp.edit().putString("server_url", v.trimEnd('/')).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v).apply()

    var speakReplies: Boolean
        get() = sp.getBoolean("speak", true)
        set(v) = sp.edit().putBoolean("speak", v).apply()

    var agentEnabled: Boolean
        get() = sp.getBoolean("agent_enabled", true)
        set(v) = sp.edit().putBoolean("agent_enabled", v).apply()

    val isConfigured: Boolean get() = serverUrl.isNotBlank()
}
"""

FILES["app/src/main/java/ai/nova/assistant/NovaApi.kt"] = """\
package ai.nova.assistant

import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Thin client for the Nova server REST + agent-polling API. */
class NovaApi(private val prefs: Prefs) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(130, TimeUnit.SECONDS)   // agent long-poll
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    private val json = "application/json; charset=utf-8".toMediaType()

    private fun req(path: String): Request.Builder {
        val b = Request.Builder().url(prefs.serverUrl.trimEnd('/') + path)
        if (prefs.token.isNotBlank()) b.header("Authorization", "Bearer ${prefs.token}")
        return b
    }

    fun health(): JSONObject = get("/api/health")

    private fun get(path: String): JSONObject {
        client.newCall(req(path).get().build()).execute().use { r ->
            val body = r.body?.string() ?: ""
            if (!r.isSuccessful) throw IOException("HTTP ${r.code}: ${body.take(200)}")
            return JSONObject(body)
        }
    }

    fun chat(message: String, session: String = "phone"): JSONObject {
        val payload = JSONObject()
            .put("message", message)
            .put("session", session)
        return post("/api/chat", payload)
    }

    private fun post(path: String, payload: JSONObject): JSONObject {
        val body = payload.toString().toRequestBody(json)
        client.newCall(req(path).post(body).build()).execute().use { r ->
            val text = r.body?.string() ?: ""
            if (!r.isSuccessful) throw IOException("HTTP ${r.code}: ${text.take(200)}")
            return JSONObject(text)
        }
    }

    /** Register this device so the server can route device actions to it. */
    fun registerAgent(name: String, capabilities: List<String>) {
        val caps = org.json.JSONArray()
        capabilities.forEach { caps.put(it) }
        post("/api/devices/register", JSONObject()
            .put("name", name)
            .put("capabilities", caps))
    }

    /** Long-poll for the next command. Returns null on timeout. */
    fun pollCommand(name: String, wait: Int = 30): JSONObject? {
        return try {
            val url = prefs.serverUrl.trimEnd('/') +
                "/api/devices/$name/next?wait=$wait"
            val b = Request.Builder().url(url)
            if (prefs.token.isNotBlank()) b.header("Authorization", "Bearer ${prefs.token}")
            client.newCall(b.build()).execute().use { r ->
                if (r.code == 204) return null
                val text = r.body?.string() ?: ""
                if (!r.isSuccessful) return null
                if (text.isBlank()) return null
                JSONObject(text)
            }
        } catch (e: Exception) {
            null
        }
    }

    fun postResult(name: String, commandId: String, ok: Boolean, output: String) {
        try {
            post("/api/devices/$name/result", JSONObject()
                .put("id", commandId)
                .put("ok", ok)
                .put("output", output.take(4000)))
        } catch (_: Exception) {
        }
    }
}
"""

FILES["app/src/main/java/ai/nova/assistant/DeviceActions.kt"] = """\
package ai.nova.assistant

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.telephony.SmsManager
import org.json.JSONObject

/** Executes the device commands the server sends to this phone. */
class DeviceActions(private val context: Context) {

    fun execute(name: String, cmd: JSONObject): String {
        val action = cmd.optString("action", cmd.optString("name", ""))
        val args = cmd.optJSONObject("args") ?: JSONObject()
        return when (action) {
            "open_app" -> openApp(args.optString("name", args.optString("package", "")))
            "open_url" -> openUrl(args.optString("url", ""))
            "send_message" -> sendSms(
                args.optString("to", ""),
                args.optString("body", args.optString("text", ""))
            )
            "open_settings" -> openSettings()
            "notify", "notification" -> "notifications are shown by the app itself"
            else -> "unsupported on phone: $action"
        }
    }

    private fun openApp(target: String): String {
        if (target.isBlank()) return "no app name given"
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(intent, 0)
        val want = target.lowercase()
        for (info in apps) {
            val label = info.loadLabel(pm).toString()
            if (label.lowercase() == want || label.lowercase().contains(want)) {
                val launch = Intent(Intent.ACTION_MAIN)
                    .addCategory(Intent.CATEGORY_LAUNCHER)
                    .setClassName(info.activityInfo.packageName, info.activityInfo.name)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launch)
                return "opened $label"
            }
        }
        return "no app matched '$target'"
    }

    private fun openUrl(url: String): String {
        if (url.isBlank()) return "no url given"
        val fixed = if (url.startsWith("http")) url else "https://$url"
        context.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(fixed))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        return "opened $fixed"
    }

    private fun sendSms(to: String, body: String): String {
        if (to.isBlank() || body.isBlank()) return "need both 'to' and 'body'"
        val sm = SmsManager.getDefault()
        val parts = sm.divideMessage(body)
        sm.sendMultipartTextMessage(to, null, parts, null, null)
        return "sent SMS to $to"
    }

    private fun openSettings(): String {
        context.startActivity(
            Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        return "opened settings"
    }
}
"""

FILES["app/src/main/java/ai/nova/assistant/DeviceAgentService.kt"] = """\
package ai.nova.assistant

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Foreground service that keeps this phone connected to Nova so it can receive
 * and run device commands in the background.
 */
class DeviceAgentService : Service() {

    private val running = AtomicBoolean(false)
    private lateinit var api: NovaApi
    private lateinit var actions: DeviceActions
    private var thread: Thread? = null

    override fun onCreate() {
        super.onCreate()
        val prefs = Prefs(this)
        api = NovaApi(prefs)
        actions = DeviceActions(this)
        startForegroundNotification()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (running.compareAndSet(false, true)) {
            thread = Thread { loop() }.also { it.isDaemon = true; it.start() }
        }
        return START_STICKY
    }

    private fun loop() {
        val name = "phone"
        val caps = listOf("open_app", "open_url", "send_message", "open_settings", "notify")
        while (running.get()) {
            try {
                api.registerAgent(name, caps)
                val cmd = api.pollCommand(name, wait = 30)
                if (cmd != null) {
                    val id = cmd.optString("id", "")
                    val output = try {
                        actions.execute(name, cmd)
                    } catch (e: Exception) {
                        "error: ${e.message}"
                    }
                    api.postResult(name, id, ok = true, output = output)
                }
            } catch (e: Exception) {
                Thread.sleep(3000)
            }
        }
    }

    private fun startForegroundNotification() {
        val channelId = "nova_agent"
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(channelId, "Nova agent", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val notif: Notification = Notification.Builder(this, channelId)
            .setContentTitle("Nova is listening")
            .setContentText("Ready to run tasks on this phone")
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .build()
        startForeground(4711, notif)
    }

    override fun onDestroy() {
        running.set(false)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
"""

FILES["app/src/main/java/ai/nova/assistant/MainActivity.kt"] = """\
package ai.nova.assistant

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var api: NovaApi
    private lateinit var tts: TextToSpeech
    private lateinit var messages: LinearLayout
    private lateinit var input: EditText
    private lateinit var scroll: ScrollView
    private lateinit var status: TextView

    private val io = Executors.newSingleThreadExecutor()
    private val history = StringBuilder()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        api = NovaApi(prefs)
        setContentView(buildUi())

        if (!prefs.isConfigured) startActivity(Intent(this, SettingsActivity::class.java))

        tts = TextToSpeech(this) { st ->
            if (st == TextToSpeech.SUCCESS) tts.language = Locale.getDefault()
        }
        requestPermissions()
        ping()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(ContextCompat.getColor(this@MainActivity, R.color.nova_bg))
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(28, 40, 28, 16)
            gravity = android.view.Gravity.CENTER_VERTICAL
        }
        val title = TextView(this).apply {
            text = "Nova"
            textSize = 22f
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.nova_text))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        status = TextView(this).apply {
            textSize = 12f
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.nova_text_dim))
        }
        val gear = TextView(this).apply {
            text = "\\u2699"
            textSize = 22f
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.nova_text_dim))
            setPadding(28, 0, 0, 0)
            setOnClickListener {
                startActivity(Intent(this@MainActivity, SettingsActivity::class.java))
            }
        }
        bar.addView(title); bar.addView(status); bar.addView(gear)
        root.addView(bar)

        scroll = ScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f
            )
        }
        messages = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(28, 8, 28, 8)
        }
        scroll.addView(messages)
        root.addView(scroll)

        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(20, 12, 20, 28)
            gravity = android.view.Gravity.CENTER_VERTICAL
        }
        val mic = TextView(this).apply {
            text = "\\uD83C\\uDF99"
            textSize = 26f
            setPadding(18, 0, 18, 0)
            setOnClickListener { listen() }
        }
        input = EditText(this).apply {
            hint = getString(R.string.hint_message)
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.nova_text))
            setHintTextColor(ContextCompat.getColor(this@MainActivity, R.color.nova_text_dim))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            imeOptions = EditorInfo.IME_ACTION_SEND
            setOnEditorActionListener { _, id, _ ->
                if (id == EditorInfo.IME_ACTION_SEND) { send(); true } else false
            }
        }
        val sendBtn = TextView(this).apply {
            text = getString(R.string.send)
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.nova_accent))
            textSize = 16f
            setPadding(24, 12, 8, 12)
            setOnClickListener { send() }
        }
        row.addView(mic); row.addView(input); row.addView(sendBtn)
        root.addView(row)
        return root
    }

    private fun requestPermissions() {
        val want = mutableListOf<String>()
        for (p in listOf(
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.SEND_SMS,
            Manifest.permission.POST_NOTIFICATIONS
        )) {
            if (ContextCompat.checkSelfPermission(this, p) != PackageManager.PERMISSION_GRANTED) {
                want.add(p)
            }
        }
        if (want.isNotEmpty()) ActivityCompat.requestPermissions(this, want.toTypedArray(), 10)
    }

    private fun ping() {
        io.execute {
            try {
                api.health()
                runOnUiThread { status.text = "online" }
            } catch (e: Exception) {
                runOnUiThread { status.text = "offline" }
            }
        }
    }

    private fun bubble(text: String, mine: Boolean) {
        val tv = TextView(this).apply {
            this.text = text
            textSize = 15f
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.nova_text))
            setPadding(28, 20, 28, 20)
            setBackgroundColor(
                ContextCompat.getColor(
                    this@MainActivity,
                    if (mine) R.color.nova_user_bubble else R.color.nova_nova_bubble
                )
            )
        }
        val lp = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT
        )
        lp.topMargin = 10
        lp.leftMargin = if (mine) 90 else 0
        lp.rightMargin = if (mine) 0 else 90
        tv.layoutParams = lp
        messages.addView(tv)
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun send() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        input.setText("")
        bubble(text, mine = true)
        history.append("You: ").append(text).append("\\n")
        io.execute {
            try {
                val reply = api.chat(text).optString("reply", "(no reply)")
                history.append("Nova: ").append(reply).append("\\n")
                runOnUiThread {
                    bubble(reply, mine = false)
                    if (prefs.speakReplies) tts.speak(reply, TextToSpeech.QUEUE_FLUSH, null, "nova")
                }
            } catch (e: Exception) {
                runOnUiThread { bubble("I could not reach my server: ${e.message}", false) }
            }
        }
    }

    private fun listen() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(); return
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak to Nova")
        }
        try {
            startActivityForResult(intent, 100)
        } catch (e: Exception) {
            Toast.makeText(this, "No speech recognizer installed", Toast.LENGTH_SHORT).show()
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 100 && resultCode == RESULT_OK) {
            val spoken = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!spoken.isNullOrBlank()) {
                input.setText(spoken)
                send()
            }
        }
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP && event?.isLongPress == true) {
            listen(); return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onDestroy() {
        io.shutdownNow()
        tts.shutdown()
        super.onDestroy()
    }
}
"""

FILES["app/src/main/java/ai/nova/assistant/SettingsActivity.kt"] = """\
package ai.nova.assistant

import android.content.Intent
import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.util.concurrent.Executors

class SettingsActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var api: NovaApi
    private val io = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        api = NovaApi(prefs)
        setContentView(buildUi())
    }

    private fun buildUi(): android.view.View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(56, 90, 56, 56)
            setBackgroundColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_bg))
        }
        fun label(t: String) = TextView(this).apply {
            text = t
            textSize = 13f
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text_dim))
            setPadding(0, 28, 0, 8)
        }
        fun field(hintRes: Int, value: String) = EditText(this).apply {
            hint = getString(hintRes)
            setText(value)
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text))
            setHintTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text_dim))
        }

        val title = TextView(this).apply {
            text = getString(R.string.settings_title)
            textSize = 22f
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text))
        }
        root.addView(title)

        root.addView(label(getString(R.string.server_url)))
        val urlField = field(R.string.server_url, prefs.serverUrl)
        root.addView(urlField)

        root.addView(label(getString(R.string.auth_token)))
        val tokenField = field(R.string.auth_token, prefs.token)
        root.addView(tokenField)

        val speak = CheckBox(this).apply {
            text = "Speak replies out loud"
            isChecked = prefs.speakReplies
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text))
        }
        root.addView(speak)

        val agent = CheckBox(this).apply {
            text = "Let Nova control this phone (background agent)"
            isChecked = prefs.agentEnabled
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text))
        }
        root.addView(agent)

        val result = TextView(this).apply {
            textSize = 13f
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text_dim))
            setPadding(0, 24, 0, 0)
        }
        root.addView(result)

        val test = Button(this).apply {
            text = getString(R.string.test_connection)
            setOnClickListener {
                io.execute {
                    try {
                        prefs.serverUrl = urlField.text.toString()
                        prefs.token = tokenField.text.toString()
                        val h = api.health()
                        runOnUiThread { result.text = "OK — ${h.optString("model", "connected")}" }
                    } catch (e: Exception) {
                        runOnUiThread { result.text = "Failed: ${e.message}" }
                    }
                }
            }
        }
        root.addView(test)

        val save = Button(this).apply {
            text = getString(R.string.save)
            setOnClickListener {
                prefs.serverUrl = urlField.text.toString()
                prefs.token = tokenField.text.toString()
                prefs.speakReplies = speak.isChecked
                prefs.agentEnabled = agent.isChecked
                if (agent.isChecked) {
                    ContextCompat.startForegroundService(
                        this@SettingsActivity, Intent(this@SettingsActivity, DeviceAgentService::class.java)
                    )
                } else {
                    stopService(Intent(this@SettingsActivity, DeviceAgentService::class.java))
                }
                finish()
            }
        }
        root.addView(save)
        return root
    }

    override fun onDestroy() {
        io.shutdownNow()
        super.onDestroy()
    }
}
"""


def main() -> None:
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print("wrote", path)


if __name__ == "__main__":
    main()
