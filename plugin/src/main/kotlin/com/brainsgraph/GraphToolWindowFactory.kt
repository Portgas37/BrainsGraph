package com.brainsgraph

import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.jcef.JBCefBrowser

class GraphToolWindowFactory : ToolWindowFactory {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val browser = JBCefBrowser()
        // Connect to the Python Backend
        browser.loadURL("http://localhost:8000") 
        toolWindow.contentManager.addContent(
            toolWindow.contentManager.factory.createContent(browser.component, "", false)
        )
    }
}