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
