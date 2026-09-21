plugins {
  id("com.tridium.niagara")
  id("com.tridium.vendor")
  id("com.tridium.niagara-signing")
  id("com.tridium.convention.niagara-home-repositories")
}

vendor {
  defaultVendor("BACTalk")
  defaultModuleVersion("0.1.0.0")
}

signingServices {
  signingProfileFactory {
    // Fail loudly instead of silently signing with the default profile.
    allowDefaultProfile.set(false)
  }
}

niagaraSigning {
  // Gate G-SDK: the human running the build supplies the alias and profile.
  aliases.set(listOf(providers.gradleProperty("bactalkSigningAlias").getOrElse("bactalk-code-cert")))
  signingProfileFile.set(
    project.layout.projectDirectory.file(
      providers.gradleProperty("bactalkSigningProfile").getOrElse("local/signing_profile.xml")
    )
  )
}

subprojects {
  repositories {
    mavenCentral()
  }
}
