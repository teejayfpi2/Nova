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
            text = "\u2699"
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
            text = "\uD83C\uDF99"
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
        history.append("You: ").append(text).append("\n")
        io.execute {
            try {
                val reply = api.chat(text).optString("reply", "(no reply)")
                history.append("Nova: ").append(reply).append("\n")
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
