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

        val aboutTitle = TextView(this).apply {
            text = getString(R.string.about_title)
            textSize = 15f
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text))
            setPadding(0, 48, 0, 8)
        }
        root.addView(aboutTitle)

        val about = TextView(this).apply {
            textSize = 13f
            setTextColor(ContextCompat.getColor(this@SettingsActivity, R.color.nova_text_dim))
            val b = StringBuilder(getString(R.string.builder_name)).append("\n")
                .append(getString(R.string.builder_email)).append("\n")
                .append(getString(R.string.builder_phone)).append("\n")
                .append(getString(R.string.builder_linkedin))
            text = b
            setOnClickListener {
                startActivity(
                    Intent(Intent.ACTION_VIEW, android.net.Uri.parse(getString(R.string.builder_linkedin)))
                )
            }
        }
        root.addView(about)

        return root
    }

    override fun onDestroy() {
        io.shutdownNow()
        super.onDestroy()
    }
}
