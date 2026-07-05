# -*- coding: utf-8 -*-
"""交互式财经英文原声精读体验页 HTML 内容 (Rich Aesthetics)

[Gemini_3.5_Flash_planning] 初始创建此文件，用于 /demo 交互演示，解耦 app.py 复杂度。
"""

HTML_CONTENT = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>暗渡成仓 - 财经英文原声交互精读体验</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;600;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #090b0f;
            --bg-card: rgba(17, 24, 39, 0.55);
            --border-glow: rgba(99, 102, 241, 0.15);
            --primary: #06b6d4;      /* 霓虹青 */
            --secondary: #6366f1;    /* 电流靛 */
            --accent: #f97316;       /* 晚霞橙 */
            --success: #10b981;      /* 极光绿 */
            --text-base: #f8fafc;
            --text-muted: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-dark);
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 80% 80%, rgba(6, 182, 212, 0.08) 0%, transparent 45%);
            background-attachment: fixed;
            color: var(--text-base);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
            display: flex;
            flex-direction: column;
        }

        /* 顶部导航 */
        header {
            width: 100%;
            padding: 1.5rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            background: rgba(9, 11, 15, 0.7);
            backdrop-filter: blur(12px);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .logo-container {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .logo-glow {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            box-shadow: 0 0 12px var(--primary);
            animation: pulse 2s infinite alternate;
        }

        .logo-text {
            font-family: 'Outfit', sans-serif;
            font-weight: 800;
            font-size: 1.4rem;
            background: linear-gradient(to right, #00f2fe, #4facfe);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: 0.5px;
        }

        .badge-demo {
            font-family: 'Fira Code', monospace;
            font-size: 0.75rem;
            padding: 0.25rem 0.6rem;
            border-radius: 99px;
            background: rgba(6, 182, 212, 0.1);
            color: var(--primary);
            border: 1px solid rgba(6, 182, 212, 0.2);
            text-transform: uppercase;
        }

        /* 响应式主体容器 */
        main {
            max-width: 1280px;
            width: 100%;
            margin: 2rem auto;
            padding: 0 1.5rem;
            display: grid;
            grid-template-columns: 2.2fr 1fr;
            gap: 2rem;
            flex-grow: 1;
        }

        @media (max-width: 1024px) {
            main {
                grid-template-columns: 1fr;
            }
        }

        /* 通用毛玻璃卡片面板 */
        .glass-panel {
            background: var(--bg-card);
            border: 1px solid var(--border-glow);
            border-radius: 20px;
            padding: 2rem;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            transition: border-color 0.3s ease, box-shadow 0.3s ease;
        }

        .glass-panel:hover {
            border-color: rgba(99, 102, 241, 0.3);
            box-shadow: 0 12px 40px 0 rgba(99, 102, 241, 0.05);
        }

        .panel-title {
            font-family: 'Outfit', sans-serif;
            font-weight: 600;
            font-size: 1.25rem;
            margin-bottom: 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 0.75rem;
        }

        /* 播放器区域 */
        .player-card {
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            align-items: center;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
            border: 1px solid rgba(255, 255, 255, 0.03);
            position: relative;
            overflow: hidden;
        }

        .player-card::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(6, 182, 212, 0.05) 0%, transparent 60%);
            pointer-events: none;
        }

        .album-art {
            width: 80px;
            height: 80px;
            border-radius: 12px;
            background: linear-gradient(45deg, #1e1b4b, #312e81);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 8px 16px rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.05);
            flex-shrink: 0;
            position: relative;
        }

        .art-icon {
            font-size: 2rem;
        }

        .player-info {
            flex-grow: 1;
        }

        .player-title {
            font-family: 'Outfit', sans-serif;
            font-weight: 600;
            font-size: 1.1rem;
            margin-bottom: 0.25rem;
            color: #fff;
        }

        .player-subtitle {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 0.75rem;
        }

        .progress-container {
            width: 100%;
            height: 4px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 99px;
            position: relative;
            cursor: pointer;
        }

        .progress-bar {
            height: 100%;
            width: 0%;
            background: linear-gradient(to right, var(--primary), var(--secondary));
            border-radius: 99px;
            position: relative;
            transition: width 0.1s linear;
        }

        .progress-bar::after {
            content: '';
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #fff;
            box-shadow: 0 0 8px var(--primary);
            position: absolute;
            right: -5px;
            top: -3px;
        }

        /* 句子交互拆解区 */
        .study-content {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        .sentence-card {
            background: rgba(30, 41, 59, 0.2);
            border: 1px solid rgba(255,255,255,0.03);
            border-radius: 14px;
            padding: 1.25rem;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
        }

        .sentence-card.active {
            border-color: rgba(6, 182, 212, 0.4);
            background: rgba(6, 182, 212, 0.03);
            box-shadow: 0 4px 20px rgba(6, 182, 212, 0.04);
        }

        .sentence-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
        }

        .sent-num {
            font-family: 'Fira Code', monospace;
            font-size: 0.8rem;
            color: var(--secondary);
            font-weight: 500;
        }

        .action-play-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px;
            padding: 0.3rem 0.6rem;
            color: #fff;
            font-size: 0.8rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.3rem;
            transition: all 0.2s ease;
        }

        .action-play-btn:hover {
            background: var(--secondary);
            border-color: var(--secondary);
            transform: translateY(-1px);
        }

        .eng-text {
            font-size: 1.25rem;
            line-height: 1.8;
            font-weight: 400;
            color: #e2e8f0;
            margin-bottom: 0.5rem;
            letter-spacing: 0.3px;
        }

        /* 卡拉OK单词标记 */
        .word-span {
            display: inline-block;
            cursor: pointer;
            padding: 0 2px;
            border-radius: 4px;
            transition: background 0.1s ease, color 0.1s ease;
        }
        .word-span:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }
        .word-span.speaking-word {
            background: rgba(6, 182, 212, 0.3);
            color: #fff;
            box-shadow: 0 0 8px rgba(6, 182, 212, 0.4);
            transform: scale(1.05);
        }

        /* 重点高亮词块 */
        .chunk {
            font-weight: 600;
            color: #00f2fe;
            border-bottom: 2px dashed rgba(6, 182, 212, 0.6);
            cursor: help;
            position: relative;
            display: inline-block;
        }

        .chunk:hover {
            color: #fff;
            background: rgba(6, 182, 212, 0.15);
        }

        .zh-text {
            font-size: 0.95rem;
            color: var(--text-muted);
            line-height: 1.6;
        }

        /* 生词浮窗 (Tooltip) */
        .tooltip-card {
            position: absolute;
            bottom: 125%;
            left: 50%;
            transform: translateX(-50%) scale(0.9);
            width: 260px;
            padding: 1rem;
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid var(--secondary);
            border-radius: 12px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5), 0 0 15px rgba(99, 102, 241, 0.3);
            z-index: 10;
            opacity: 0;
            pointer-events: none;
            transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        .chunk:hover .tooltip-card {
            opacity: 1;
            transform: translateX(-50%) scale(1);
            pointer-events: auto;
        }

        .tool-title {
            font-weight: 600;
            font-size: 0.95rem;
            color: var(--primary);
            margin-bottom: 0.25rem;
        }
        .tool-meaning {
            font-size: 0.85rem;
            color: #fff;
            margin-bottom: 0.5rem;
        }
        .tool-usage {
            font-size: 0.75rem;
            color: var(--text-muted);
            border-top: 1px solid rgba(255,255,255,0.05);
            padding-top: 0.4rem;
            font-style: italic;
        }

        /* 右侧边栏 */
        .right-sidebar {
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }

        /* 生词册 */
        .vocab-list {
            margin-top: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            max-height: 250px;
            overflow-y: auto;
            padding-right: 0.25rem;
        }

        .vocab-item {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            padding: 0.75rem 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            animation: slideIn 0.3s cubic-bezier(0.18, 0.89, 0.32, 1.28) forwards;
        }

        @keyframes slideIn {
            from { opacity: 0; transform: translateX(30px); }
            to { opacity: 1; transform: translateX(0); }
        }

        .vocab-info .vocab-word {
            font-weight: 600;
            font-size: 0.95rem;
            color: var(--accent);
        }
        .vocab-info .vocab-trans {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 0.15rem;
        }

        .vocab-del-btn {
            background: none;
            border: none;
            color: rgba(239, 68, 68, 0.6);
            cursor: pointer;
            font-size: 0.8rem;
            transition: color 0.2s ease;
        }
        .vocab-del-btn:hover {
            color: rgba(239, 68, 68, 1);
        }

        .empty-vocab {
            text-align: center;
            color: var(--text-muted);
            font-size: 0.85rem;
            padding: 2rem 0;
            border: 1px dashed rgba(255, 255, 255, 0.05);
            border-radius: 10px;
        }

        /* 听力挖空游戏 */
        .cloze-container {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .cloze-sentence {
            font-size: 0.95rem;
            line-height: 1.6;
            color: #cbd5e1;
            background: rgba(255,255,255,0.02);
            padding: 0.85rem;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.03);
        }

        .cloze-input {
            width: 90px;
            background: rgba(9, 11, 15, 0.6);
            border: 1px solid var(--border-glow);
            border-radius: 4px;
            padding: 0.15rem 0.4rem;
            color: #fff;
            font-family: 'Fira Code', monospace;
            text-align: center;
            font-size: 0.9rem;
            transition: all 0.3s ease;
            outline: none;
        }

        .cloze-input:focus {
            border-color: var(--secondary);
            box-shadow: 0 0 8px rgba(99, 102, 241, 0.4);
        }

        .cloze-input.correct {
            border-color: var(--success);
            color: var(--success);
            box-shadow: 0 0 10px rgba(16, 185, 129, 0.4);
            animation: bounceInput 0.4s ease;
        }

        @keyframes bounceInput {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.1); }
        }

        .check-btn {
            width: 100%;
            background: linear-gradient(135deg, var(--secondary), #4f46e5);
            color: #fff;
            border: none;
            padding: 0.75rem;
            border-radius: 10px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 0.5rem;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
        }

        .check-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(99, 102, 241, 0.35);
        }

        /* 录音与影子跟读 */
        .record-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1.25rem;
            margin-top: 1rem;
        }

        .record-btn-container {
            position: relative;
        }

        .record-circle {
            width: 70px;
            height: 70px;
            border-radius: 50%;
            background: linear-gradient(135deg, #ef4444, #dc2626);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 0 15px rgba(239, 68, 68, 0.4);
            transition: all 0.3s ease;
            border: none;
            outline: none;
        }

        .record-circle:hover {
            transform: scale(1.05);
            box-shadow: 0 0 25px rgba(239, 68, 68, 0.6);
        }

        .record-circle.recording {
            animation: pulseRecord 1.5s infinite;
            background: linear-gradient(135deg, #f59e0b, #d97706);
            box-shadow: 0 0 25px rgba(245, 158, 11, 0.6);
        }

        @keyframes pulseRecord {
            0% { transform: scale(1); box-shadow: 0 0 15px rgba(245, 158, 11, 0.4); }
            50% { transform: scale(1.08); box-shadow: 0 0 35px rgba(245, 158, 11, 0.8); }
            100% { transform: scale(1); box-shadow: 0 0 15px rgba(245, 158, 11, 0.4); }
        }

        .mic-icon {
            font-size: 1.8rem;
            color: #fff;
        }

        /* 录音波形动画 */
        .wave-animation {
            display: flex;
            align-items: center;
            gap: 4px;
            height: 30px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .wave-animation.active {
            opacity: 1;
        }

        .wave-bar {
            width: 3px;
            height: 5px;
            background: var(--accent);
            border-radius: 99px;
            animation: wave 1.2s ease-in-out infinite alternate;
        }

        .wave-bar:nth-child(2) { animation-delay: 0.1s; height: 12px; }
        .wave-bar:nth-child(3) { animation-delay: 0.25s; height: 22px; }
        .wave-bar:nth-child(4) { animation-delay: 0.15s; height: 16px; }
        .wave-bar:nth-child(5) { animation-delay: 0.35s; height: 8px; }

        @keyframes wave {
            0% { transform: scaleY(1); }
            100% { transform: scaleY(4); }
        }

        /* 评分环 */
        .score-display {
            display: none;
            text-align: center;
            animation: fadeIn 0.4s ease forwards;
        }

        .score-circle {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            border: 6px solid var(--border-glow);
            border-top-color: var(--success);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            margin: 0 auto 0.75rem auto;
            position: relative;
        }

        .score-num {
            font-family: 'Outfit', sans-serif;
            font-weight: 800;
            font-size: 2rem;
            color: var(--success);
        }

        .score-label {
            font-size: 0.7rem;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .score-detail {
            font-size: 0.8rem;
            color: var(--text-muted);
            line-height: 1.5;
        }

        .score-detail span {
            color: #fff;
            font-weight: 500;
        }

        /* 磨砂加载器 */
        .loader-backdrop {
            display: none;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 1rem;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid rgba(255,255,255,0.05);
            border-top-color: var(--primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .loader-text {
            font-size: 0.85rem;
            color: var(--text-muted);
            font-family: 'Fira Code', monospace;
        }

        /* Export ANKI 按钮 */
        .export-btn {
            background: rgba(249, 115, 22, 0.1);
            color: var(--accent);
            border: 1px solid rgba(249, 115, 22, 0.2);
            padding: 0.6rem 1rem;
            border-radius: 10px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.4rem;
            width: 100%;
            margin-top: 1rem;
        }

        .export-btn:hover:not(:disabled) {
            background: var(--accent);
            color: #fff;
            border-color: var(--accent);
            transform: translateY(-1px);
        }

        .export-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Confetti 特效画布粒子 */
        .confetti-particle {
            position: fixed;
            width: 8px;
            height: 8px;
            z-index: 999;
            pointer-events: none;
            opacity: 0.8;
            animation: dropConfetti 3s ease-out forwards;
        }

        @keyframes dropConfetti {
            0% { transform: translateY(-5vh) rotate(0deg); opacity: 1; }
            100% { transform: translateY(105vh) rotate(720deg); opacity: 0; }
        }

        @keyframes pulse {
            0% { transform: scale(1); box-shadow: 0 0 8px var(--primary); }
            100% { transform: scale(1.2); box-shadow: 0 0 16px var(--primary); }
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        footer {
            text-align: center;
            padding: 2rem;
            font-size: 0.8rem;
            color: rgba(255,255,255,0.15);
            border-top: 1px solid rgba(255,255,255,0.02);
            margin-top: auto;
        }
    </style>
</head>
<body>

    <header>
        <div class="logo-container">
            <div class="logo-glow"></div>
            <span class="logo-text">ANDUCHENCANG</span>
            <span class="badge-demo">PROTOTYPE v1.0</span>
        </div>
        <div style="font-size: 0.85rem; color: var(--text-muted);">
            视频号财经英文原声精读交互版
        </div>
    </header>

    <main>
        <!-- 左侧主体 -->
        <div style="display: flex; flex-direction: column; gap: 2rem;">
            <!-- 播放器 -->
            <div class="player-card">
                <div class="album-art">
                    <span class="art-icon">🎙️</span>
                </div>
                <div class="player-info">
                    <div class="player-title">Why Markets Are Betting on Rate Cuts</div>
                    <div class="player-subtitle">美联储降息预期与通胀博弈 • 英文原声精听</div>
                    <div class="progress-container" id="progressBarContainer">
                        <div class="progress-bar" id="progressBar"></div>
                    </div>
                </div>
            </div>

            <!-- 精读区 -->
            <div class="glass-panel">
                <div class="panel-title">
                    <span>📖</span> 财经原声逐句精读 (点击单词可收集)
                </div>

                <div class="study-content">
                    <!-- 句子一 -->
                    <div class="sentence-card active" id="sent-1">
                        <div class="sentence-header">
                            <span class="sent-num">SENTENCE 01</span>
                            <button class="action-play-btn" onclick="playSentence(1)">
                                🔊 播放原音
                            </button>
                        </div>
                        <div class="eng-text" id="eng-text-1">
                            <!-- JS 会在此处渲染出独立的 word spans -->
                        </div>
                        <div class="zh-text">
                            市场目前正在将经济“软着陆”预期计入资产价格，然而居高不下的粘性通胀依然让美联储保持了极其审慎的态度。
                        </div>
                    </div>

                    <!-- 句子二 -->
                    <div class="sentence-card" id="sent-2">
                        <div class="sentence-header">
                            <span class="sent-num">SENTENCE 02</span>
                            <button class="action-play-btn" onclick="playSentence(2)">
                                🔊 播放原音
                            </button>
                        </div>
                        <div class="eng-text" id="eng-text-2">
                            <!-- JS 会在此处渲染出独立的 word spans -->
                        </div>
                        <div class="zh-text">
                            就业市场的温和降温或许能够为政策制定者们在后续暂停行动时提供所需的政策缓冲与理由。
                        </div>
                    </div>
                </div>
            </div>

            <!-- 跟读评测 -->
            <div class="glass-panel">
                <div class="panel-title">
                    <span>🎙️</span> 口语影子跟读评测 (Shadowing AI)
                </div>
                <div style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 1rem;">
                    请选择上方高亮的句子，点击下方麦克风开始录音跟读，系统将通过 AI 进行口语打分。
                </div>

                <div class="record-container">
                    <div class="record-btn-container">
                        <button class="record-circle" id="recordBtn" onclick="toggleRecording()">
                            <span class="mic-icon" id="recordIcon">🎤</span>
                        </button>
                    </div>

                    <!-- 律动音浪 -->
                    <div class="wave-animation" id="waveAnim">
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                        <div class="wave-bar"></div>
                    </div>

                    <!-- 磨砂加载 -->
                    <div class="loader-backdrop" id="loader">
                        <div class="spinner"></div>
                        <div class="loader-text">AI 语音评测引擎分析中...</div>
                    </div>

                    <!-- 评分结果 -->
                    <div class="score-display" id="scoreDisplay">
                        <div class="score-circle">
                            <span class="score-num" id="scoreNum">94</span>
                            <span class="score-label">Score</span>
                        </div>
                        <div class="score-detail">
                            🎉 评测表现优异！发音 <span>92</span> | 流利度 <span>95</span> | 完整度 <span>95</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 右侧边栏 -->
        <div class="right-sidebar">
            <!-- 听力挖空 -->
            <div class="glass-panel">
                <div class="panel-title">
                    <span>🧩</span> 听力挖空填词挑战 (Cloze Test)
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1.25rem;">
                    边听原音边完成填空，检测关键财经词块的听写能力。
                </div>

                <div class="cloze-container">
                    <div class="cloze-sentence">
                        1. Markets are <input type="text" class="cloze-input" id="c1" placeholder="pricing"> in a soft landing...
                    </div>
                    <div class="cloze-sentence">
                        2. but <input type="text" class="cloze-input" id="c2" placeholder="sticky"> inflation keeps the Fed cautious.
                    </div>
                    <button class="check-btn" onclick="checkCloze()">验证听写答案</button>
                </div>
            </div>

            <!-- 今日单词册 -->
            <div class="glass-panel">
                <div class="panel-title">
                    <span>📓</span> 我的生词卡夹 (<span id="vocabCount">0</span>)
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted);">
                    点击句子中带有虚线的词块或普通单词，将其收集到你的专属 Anki 记忆卡中。
                </div>

                <div class="vocab-list" id="vocabList">
                    <div class="empty-vocab" id="emptyVocab">
                        生词卡夹空空如也，点击词汇开始收集吧
                    </div>
                </div>

                <button class="export-btn" id="exportBtn" onclick="exportToAnki()" disabled>
                    📥 导出为 Anki 记忆卡包
                </button>
            </div>
        </div>
    </main>

    <footer>
        Antigravity - 暗渡成仓水下工程 • WeChat Channels Automated Publishing Pipeline © 2026
    </footer>

    <script>
        // 1. 句子源数据
        const DATA = {
            1: {
                text: "Markets are pricing in a soft landing, but sticky inflation keeps the Fed cautious.",
                chunks: {
                    "pricing in": { trans: "将...计入资产价格", usage: "Markets are pricing in a rate cut." },
                    "soft landing": { trans: "经济软着陆", usage: "The Fed aims for a soft landing." },
                    "sticky inflation": { trans: "黏性通胀 (价格难以回落)", usage: "Sticky inflation is a headache for policymakers." }
                }
            },
            2: {
                text: "A cooling labor market could give policymakers the cover they need to pause.",
                chunks: {
                    "cooling labor market": { trans: "降温的就业市场", usage: "Signs of a cooling labor market are emerging." },
                    "policymakers": { trans: "政策制定者 (通常指美联储委员)", usage: "Policymakers gather to discuss interest rates." },
                    "the cover": { trans: "政策上的合理借口/缓冲", usage: "Weak retail sales gave the bank the cover to cut." }
                }
            }
        };

        let myVocab = new Set();
        let isRecording = false;
        let speechTimeout = null;
        let activeSentence = 1;

        // 2. 初始化句子拆解渲染
        function initSentences() {
            renderSentence(1);
            renderSentence(2);
        }

        function renderSentence(id) {
            const container = document.getElementById(`eng-text-${id}`);
            const data = DATA[id];
            let html = "";
            
            // 简单匹配词块并分词
            const text = data.text;
            const chunksKeys = Object.keys(data.chunks);
            
            // 极简切词逻辑
            let words = text.split(" ");
            let i = 0;
            while(i < words.length) {
                // 试着匹配双词词块
                let doubleWord = (words[i] + " " + (words[i+1] || "")).replace(/[,.]/g, "").trim();
                // 试着匹配三词词块
                let tripleWord = (words[i] + " " + (words[i+1] || "") + " " + (words[i+2] || "")).replace(/[,.]/g, "").trim();
                
                if (chunksKeys.includes(tripleWord)) {
                    html += `<span class="chunk" onclick="collectWord('${tripleWord}', ${id})">${words[i]} ${words[i+1]} ${words[i+2]}
                        <span class="tooltip-card">
                            <div class="tool-title">${tripleWord}</div>
                            <div class="tool-meaning">${data.chunks[tripleWord].trans}</div>
                            <div class="tool-usage">例句: ${data.chunks[tripleWord].usage}</div>
                        </span>
                    </span> `;
                    i += 3;
                } else if (chunksKeys.includes(doubleWord)) {
                    html += `<span class="chunk" onclick="collectWord('${doubleWord}', ${id})">${words[i]} ${words[i+1]}
                        <span class="tooltip-card">
                            <div class="tool-title">${doubleWord}</div>
                            <div class="tool-meaning">${data.chunks[doubleWord].trans}</div>
                            <div class="tool-usage">例句: ${data.chunks[doubleWord].usage}</div>
                        </span>
                    </span> `;
                    i += 2;
                } else {
                    let cleanWord = words[i].replace(/[,.]/g, "");
                    html += `<span class="word-span" onclick="collectWord('${cleanWord}', ${id})">${words[i]}</span> `;
                    i += 1;
                }
            }
            container.innerHTML = html;
        }

        // 3. 收集生词
        function collectWord(word, sentId) {
            word = word.replace(/[,.]/g, "").trim();
            if (myVocab.has(word)) return;
            
            myVocab.add(word);
            updateVocabPanel();
        }

        function removeVocab(word) {
            myVocab.delete(word);
            updateVocabPanel();
        }

        function updateVocabPanel() {
            const listContainer = document.getElementById("vocabList");
            const countLabel = document.getElementById("vocabCount");
            const exportBtn = document.getElementById("exportBtn");
            
            countLabel.innerText = myVocab.size;
            
            if (myVocab.size === 0) {
                listContainer.innerHTML = `
                    <div class="empty-vocab" id="emptyVocab">
                        生词卡夹空空如也，点击词汇开始收集吧
                    </div>`;
                exportBtn.disabled = true;
                return;
            }
            
            exportBtn.disabled = false;
            let html = "";
            myVocab.forEach(word => {
                let meaning = "普通单词";
                // 查找是否在词块预设库
                for(let sid in DATA) {
                    if (DATA[sid].chunks[word]) {
                        meaning = DATA[sid].chunks[word].trans;
                        break;
                    }
                }
                html += `
                    <div class="vocab-item">
                        <div class="vocab-info">
                            <div class="vocab-word">${word}</div>
                            <div class="vocab-trans">${meaning}</div>
                        </div>
                        <button class="vocab-del-btn" onclick="removeVocab('${word}')">✕</button>
                    </div>`;
            });
            listContainer.innerHTML = html;
        }

        // 4. Anki 模拟导出
        function exportToAnki() {
            alert(`🎉 成功将 ${myVocab.size} 个生词打包为 Anki 格式!\\n[Markets_Betting_Rate_Cuts.apkg] 已成功下载至本地，并在服务器生成同步记录。`);
            myVocab.clear();
            updateVocabPanel();
            triggerConfetti();
        }

        // 5. 逐句发音与边界高亮
        function playSentence(id) {
            activeSentence = id;
            document.querySelectorAll(".sentence-card").forEach(c => c.classList.remove("active"));
            document.getElementById(`sent-${id}`).classList.add("active");

            const data = DATA[id];
            const text = data.text;
            const progressBar = document.getElementById("progressBar");
            
            // 切换进度条动画
            progressBar.style.width = "0%";
            let start = null;
            const duration = id === 1 ? 5500 : 5000; // 模拟时长
            
            function step(timestamp) {
                if (!start) start = timestamp;
                let progress = timestamp - start;
                let pct = Math.min((progress / duration) * 100, 100);
                progressBar.style.width = pct + "%";
                if (pct < 100) {
                    requestAnimationFrame(step);
                }
            }
            requestAnimationFrame(step);

            // 浏览器语音合成
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.lang = 'en-US';
                utterance.rate = 0.85;

                // 尝试找出高质量美音
                const voices = window.speechSynthesis.getVoices();
                const preferredVoice = voices.find(v => 
                    v.name.includes("Siri") || 
                    v.name.includes("Samantha") || 
                    v.name.includes("Google US English") || 
                    v.name.includes("Microsoft Zira")
                );
                if (preferredVoice) utterance.voice = preferredVoice;

                // 卡拉ok高亮词界检测
                const container = document.getElementById(`eng-text-${id}`);
                const spanElements = container.querySelectorAll(".word-span, .chunk");
                
                utterance.onboundary = function(event) {
                    if (event.name === 'word') {
                        // 根据字符边界索引定位当前朗读单词
                        let charIdx = event.charIndex;
                        let textAccumulator = 0;
                        
                        spanElements.forEach((el) => {
                            let cleanText = el.innerText.trim();
                            let elStart = text.indexOf(cleanText, textAccumulator);
                            
                            if (elStart !== -1) {
                                textAccumulator = elStart + cleanText.length;
                                if (charIdx >= elStart && charIdx < textAccumulator) {
                                    el.classList.add("speaking-word");
                                } else {
                                    el.classList.remove("speaking-word");
                                }
                            }
                        });
                    }
                };

                utterance.onend = function() {
                    spanElements.forEach(el => el.classList.remove("speaking-word"));
                    progressBar.style.width = "100%";
                };

                window.speechSynthesis.speak(utterance);
            } else {
                alert("当前浏览器不支持 SpeechSynthesis 发音，已模拟播放。");
            }
        }

        // 6. 听力填空校验
        function checkCloze() {
            const c1 = document.getElementById("c1");
            const c2 = document.getElementById("c2");
            let allCorrect = true;

            if (c1.value.toLowerCase().trim() === "pricing") {
                c1.classList.add("correct");
            } else {
                c1.classList.remove("correct");
                allCorrect = false;
            }

            if (c2.value.toLowerCase().trim() === "sticky") {
                c2.classList.add("correct");
            } else {
                c2.classList.remove("correct");
                allCorrect = false;
            }

            if (allCorrect) {
                triggerConfetti();
                setTimeout(() => alert("🎉 太棒了，全部听写正确！高亮词块记忆达成！"), 200);
            } else {
                alert("听写有误，再仔细听听发音试试！");
            }
        }

        // 7. 跟读录音与 AI 影子评分仿真
        function toggleRecording() {
            const btn = document.getElementById("recordBtn");
            const icon = document.getElementById("recordIcon");
            const wave = document.getElementById("waveAnim");
            const loader = document.getElementById("loader");
            const scoreDisplay = document.getElementById("scoreDisplay");

            if (!isRecording) {
                // 开启录音模拟
                isRecording = true;
                btn.classList.add("recording");
                icon.innerText = "⏹️";
                wave.classList.add("active");
                scoreDisplay.style.display = "none";
                loader.style.display = "none";
            } else {
                // 停止录音，开始分析
                isRecording = false;
                btn.classList.remove("recording");
                icon.innerText = "🎤";
                wave.classList.remove("active");
                
                // 加载中动画
                loader.style.display = "flex";
                
                setTimeout(() => {
                    loader.style.display = "none";
                    scoreDisplay.style.display = "block";
                    
                    // 随机评分
                    const score = Math.floor(Math.random() * 8) + 90; // 90~97
                    document.getElementById("scoreNum").innerText = score;
                    triggerConfetti();
                }, 2000);
            }
        }

        // 8. 炫酷飘落彩屑 Confetti
        function triggerConfetti() {
            const colors = ['#06b6d4', '#6366f1', '#f97316', '#10b981', '#f43f5e', '#eab308'];
            for (let i = 0; i < 50; i++) {
                const el = document.createElement("div");
                el.classList.add("confetti-particle");
                el.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
                el.style.left = Math.random() * 100 + "vw";
                el.style.width = (Math.random() * 8 + 6) + "px";
                el.style.height = (Math.random() * 12 + 6) + "px";
                
                // 随机降落持续时间及倾角
                const dur = Math.random() * 1.5 + 1.5;
                el.style.animationDuration = dur + "s";
                el.style.transform = `rotate(${Math.random() * 360}deg)`;
                
                document.body.appendChild(el);
                
                // 结束后移除
                setTimeout(() => {
                    el.remove();
                }, dur * 1000);
            }
        }

        // 初始化
        window.addEventListener('load', () => {
            initSentences();
            // 在 iOS 上有些语音合成需要预先触发
            window.speechSynthesis.getVoices();
        });
    </script>
</body>
</html>
"""
