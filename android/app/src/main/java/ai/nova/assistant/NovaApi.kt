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
