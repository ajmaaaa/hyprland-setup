import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import Quickshell.Io

ShellRoot {
    id: root
    property bool shown: false
    property bool ready: false
    readonly property var monitor: Hyprland.focusedMonitor
    readonly property var workspace: monitor ? monitor.activeWorkspace : null
    readonly property int activeId: workspace ? workspace.id : -1
    readonly property var workspaceIds: Hyprland.workspaces.values
        .filter(w => w.id > 0 && w.monitor && monitor && w.monitor.id === monitor.id)
        .map(w => w.id).sort((a, b) => a - b)
    readonly property int activeIndex: workspaceIds.indexOf(activeId)

    function show() {
        if (!ready || activeId < 1) return;
        Hyprland.refreshToplevels();
        shown = true;
        dismiss.restart();
    }
    onActiveIdChanged: show()
    Component.onCompleted: ready = true

    Timer {
        id: dismiss
        interval: 1000
        onTriggered: root.shown = false
    }
    // Refresh geometry only while the overlay is on screen.
    Timer {
        interval: 400
        repeat: true
        running: root.shown
        onTriggered: Hyprland.refreshToplevels()
    }
    IpcHandler {
        target: "preview"
        function reveal(): void { root.show(); }
        function hide(): void { root.shown = false; dismiss.stop(); }
        function status(): string {
            return JSON.stringify({ shown: root.shown, workspace: root.activeId,
                workspaces: root.workspaceIds, monitor: root.monitor ? root.monitor.name : "" });
        }
    }

    PanelWindow {
        id: panel
        screen: Quickshell.screens.find(s => root.monitor && s.name === root.monitor.name) ?? null
        anchors.right: true
        margins.right: 24
        implicitWidth: 296
        implicitHeight: 550
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "workspace-preview"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        // The overlay must never swallow clicks or keyboard focus.
        mask: Region {}
        visible: contents.opacity > 0

        Item {
            id: contents
            anchors.fill: parent
            opacity: root.shown ? 1 : 0
            transform: Translate { x: root.shown ? 0 : 18; Behavior on x { NumberAnimation { duration: 170 } } }
            Behavior on opacity { NumberAnimation { duration: 170 } }

            Repeater {
                model: Hyprland.workspaces
                delegate: Item {
                    id: card
                    required property var modelData
                    readonly property int wsIndex: root.workspaceIds.indexOf(modelData.id)
                    readonly property int offset: wsIndex - root.activeIndex
                    readonly property bool inRange: wsIndex >= 0 && Math.abs(offset) <= 1
                    readonly property bool selected: modelData.id === root.activeId
                    readonly property var sourceMonitor: modelData.monitor
                    readonly property var monitorData: sourceMonitor ? sourceMonitor.lastIpcObject : ({})
                    readonly property bool rotated: [1, 3, 5, 7].includes(monitorData.transform ?? 0)
                    readonly property real monitorWidth: Math.max(1, sourceMonitor
                        ? (rotated ? sourceMonitor.height : sourceMonitor.width) / sourceMonitor.scale : 1920)
                    readonly property real monitorHeight: Math.max(1, sourceMonitor
                        ? (rotated ? sourceMonitor.width : sourceMonitor.height) / sourceMonitor.scale : 1080)
                    width: 264
                    height: previewHeight
                    readonly property real previewHeight: Math.min(190, width * monitorHeight / monitorWidth)
                    x: parent.width - width - 16
                    transformOrigin: Item.Right
                    y: (parent.height - height) / 2 + Math.max(-2, Math.min(2, offset)) * (height * 0.88 + 13)
                    scale: selected ? 1 : 0.76
                    opacity: inRange ? 1 : 0
                    visible: opacity > 0
                    z: selected ? 2 : 1
                    Behavior on y { NumberAnimation { duration: 230; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 230; easing.type: Easing.OutCubic } }
                    Behavior on opacity { NumberAnimation { duration: 180 } }

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: -4
                        radius: 13
                        color: "transparent"
                        border.color: card.selected ? "#c9def5" : "#59616e"
                        border.width: card.selected ? 2 : 1
                    }

                    Rectangle {
                        id: desktop
                        width: parent.width
                        height: card.previewHeight
                        color: "#000000"
                        clip: true
                        // Preserve each window's position and dimensions on its desktop.
                        Loader {
                            anchors.fill: parent
                            active: panel.visible && card.visible
                            sourceComponent: Component {
                                Item {
                                    Repeater {
                                        model: card.modelData.toplevels
                                        delegate: Item {
                                            id: windowItem
                                            required property var modelData
                                            readonly property var details: modelData.lastIpcObject ?? ({})
                                            readonly property var position: details.at ?? [0, 0]
                                            readonly property var dimensions: details.size ?? [1, 1]
                                            readonly property real ratio: Math.min(desktop.width / card.monitorWidth, desktop.height / card.monitorHeight)
                                            x: (position[0] - (card.sourceMonitor ? card.sourceMonitor.x : 0)) * ratio
                                            y: (position[1] - (card.sourceMonitor ? card.sourceMonitor.y : 0)) * ratio
                                            width: dimensions[0] * ratio
                                            height: dimensions[1] * ratio
                                            visible: details.mapped !== false && details.hidden !== true
                                            z: (details.fullscreen ? 10000 : details.floating ? 1000 : 0)
                                                + 100 - Math.min(100, details.focusHistoryID ?? 100)
                                            ScreencopyView {
                                                id: capture
                                                anchors.fill: parent
                                                captureSource: windowItem.modelData.wayland
                                                live: false
                                                paintCursor: false
                                                // Downsample from the captured source resolution,
                                                // not an already thumbnail-sized intermediate texture.
                                                layer.enabled: hasContent
                                                layer.textureSize: sourceSize
                                                layer.mipmap: true
                                                layer.smooth: true
                                                Timer {
                                                    interval: 125
                                                    repeat: true
                                                    running: root.shown && windowItem.visible && capture.hasContent
                                                    onTriggered: capture.captureFrame()
                                                }
                                            }
                                            Text {
                                                anchors.centerIn: parent
                                                width: parent.width - 12
                                                horizontalAlignment: Text.AlignHCenter
                                                elide: Text.ElideRight
                                                text: windowItem.details.class ?? ""
                                                color: "#bdc7d4"
                                                font.pixelSize: 12
                                                visible: !capture.hasContent
                                            }
                                        }
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        text: "Kosong"
                                        color: "#7c8696"
                                        font.pixelSize: 13
                                        visible: card.modelData.toplevels.values.length === 0
                                    }
                                }
                            }
                        }
                    }
                    Rectangle {
                        anchors.fill: desktop
                        color: "black"
                        opacity: card.offset > 0 ? 0.16 : 0
                        Behavior on opacity { NumberAnimation { duration: 180 } }
                    }
                    Text {
                        x: 10
                        y: desktop.height - height - 10
                        text: "Workspace " + card.modelData.name
                        color: card.selected ? "#ffffff" : "#c1cad7"
                        font.pixelSize: 13
                        style: Text.Outline
                        styleColor: "#90000000"
                        font.weight: card.selected ? Font.DemiBold : Font.Normal
                    }

                }
            }
        }
    }
}
