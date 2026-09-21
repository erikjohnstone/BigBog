import com.tridium.gradle.plugins.module.util.ModulePart.RuntimeProfile.*

plugins {
  id("com.tridium.niagara-module")
  id("com.tridium.niagara-signing")
  id("com.tridium.convention.niagara-home-repositories")
}

description = "BACTalk Guideline 36 kernel blocks (Workbench palette)"

moduleManifest {
  moduleName.set("bactalkG36")
  runtimeProfile.set(wb)
}

dependencies {
  nre(":nre")
  api(":baja")
  api(":bactalkG36-rt")
  api(":workbench-wb")
}
