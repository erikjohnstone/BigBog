import com.tridium.gradle.plugins.module.util.ModulePart.RuntimeProfile.*

plugins {
  id("com.tridium.niagara-module")
  id("com.tridium.niagara-signing")
  id("com.tridium.bajadoc")
  id("com.tridium.niagara-jacoco")
  id("com.tridium.convention.niagara-home-repositories")
}

description = "BACTalk Guideline 36 kernel blocks (runtime)"

moduleManifest {
  moduleName.set("bactalkG36")
  runtimeProfile.set(rt)
}

dependencies {
  // NRE dependencies
  nre(":nre")

  // Niagara module dependencies: only baja (sys and status) is used.
  api(":baja")

  // Tests run through the Niagara test harness once Gate G-SDK passes.
  moduleTestImplementation(":test-wb")
}
