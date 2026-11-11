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
        post("/api/devices/$name/hello", JSONObject()
            .put("capabilities", capsArray(capabilities)))
    }

    private fun capsArray(capabilities: List<String>): org.json.JSONArray {
        val caps = org.json.JSONArray()
        capabilities.forEach { caps.put(it) }
        return caps
    }

    /** Poll for the next command. Returns null when there is nothing to do. */
    fun pollCommand(name: String, capabilities: List<String>, wait: Int = 30): JSONObject? {
        return try {
            val payload = JSONObject()
                .put("name", name)
                .put("capabilities", capsArray(capabilities))
            val job = post("/api/bridge/poll", payload).optJSONObject("job") ?: return null
            if (job.length() == 0) null else job
        } catch (e: Exception) {
            null
        }
    }

    fun postResult(name: String, commandId: String, ok: Boolean, output: String) {
        try {
            val result = if (ok) output else "error: $output"
            post("/api/bridge/result", JSONObject()
                .put("name", name)
                .put("id", commandId)
                .put("result", result.take(2000)))
        } catch (_: Exception) {
        }
    }
}
