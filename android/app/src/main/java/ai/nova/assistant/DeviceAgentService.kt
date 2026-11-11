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
