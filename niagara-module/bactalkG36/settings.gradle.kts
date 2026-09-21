/*
 * bactalkG36: BACTalk's Guideline 36 kernel blocks for Niagara 4.
 *
 * Mirrors the nhaystack layout (settings plugins from the Niagara SDK). Building
 * requires a licensed Workbench with the SDK; see gates/G-SDK.md. CI compiles the
 * sources against stub interfaces only (niagara-module/stubs).
 */

import com.tridium.gradle.plugins.settings.MultiProjectExtension
import com.tridium.gradle.plugins.settings.LocalSettingsExtension

pluginManagement {
  val niagaraHome: Provider<String> = providers.gradleProperty("niagara_home").orElse(
    providers.systemProperty("niagara_home").orElse(
      providers.environmentVariable("NIAGARA_HOME").orElse(
        providers.environmentVariable("niagara_home")
      )
    )
  )

  val gradlePluginHome: String = providers.gradleProperty("gradlePluginHome").orElse(
    providers.environmentVariable("GRADLE_PLUGIN_HOME").orElse(
      niagaraHome.map { "$it/etc/m2/repository" }
    )
  ).orNull ?: throw InvalidUserDataException(
    "Set niagara_home (or NIAGARA_HOME) to a Niagara 4 installation with the SDK; " +
      "see gradle.properties and gates/G-SDK.md."
  )

  val gradlePluginRepoUrl = "file:///${gradlePluginHome.replace('\\', '/')}"
  val gradlePluginVersion: String = "7.6.22"
  val settingsPluginVersion: String = "7.6.3"

  repositories {
    maven(url = gradlePluginRepoUrl)
    mavenLocal()
    gradlePluginPortal()
  }

  plugins {
    id("com.tridium.settings.multi-project") version (settingsPluginVersion)
    id("com.tridium.settings.local-settings-convention") version (settingsPluginVersion)
    id("com.tridium.niagara") version (gradlePluginVersion)
    id("com.tridium.vendor") version (gradlePluginVersion)
    id("com.tridium.niagara-module") version (gradlePluginVersion)
    id("com.tridium.niagara-signing") version (gradlePluginVersion)
    id("com.tridium.convention.niagara-home-repositories") version (gradlePluginVersion)
  }
}

plugins {
  id("com.tridium.settings.multi-project")
  id("com.tridium.settings.local-settings-convention")
}

configure<LocalSettingsExtension> {
  loadLocalSettings()
}

configure<MultiProjectExtension> {
  findProjects()
}

rootProject.name = "bactalkG36"
