plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ai.nova.assistant"
    compileSdk = 34

    defaultConfig {
        applicationId = "ai.nova.assistant"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "1.1"
    }

    // A fixed signing key so every build (local and CI) shares one signature.
    // Without this, Gradle generates a fresh debug keystore per machine/run and
    // Android rejects updates with "App not installed" (signature mismatch).
    signingConfigs {
        create("nova") {
            val ks = rootProject.file("nova-debug.keystore")
            if (ks.exists()) {
                storeFile = ks
                storePassword = "android"
                keyAlias = "novadebug"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        getByName("debug") {
            val nova = signingConfigs.getByName("nova")
            if (nova.storeFile != null) signingConfig = nova
        }
        release {
            isMinifyEnabled = false
            val nova = signingConfigs.getByName("nova")
            signingConfig = if (nova.storeFile != null) nova else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.json:json:20240303")
}
