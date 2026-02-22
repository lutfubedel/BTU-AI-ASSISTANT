<!DOCTYPE html>
<html lang="tr" class="h-full">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>BTU AI Asistan</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="style.css">
</head>

<body class="h-full bg-[#212121] text-gray-200 font-sans flex flex-col overflow-hidden">

    <header
        class="bg-[#212121] border-b border-white/10 h-16 flex items-center justify-between px-6 z-30 flex-shrink-0">
        <div class="flex items-center space-x-3">
            <div class="w-9 h-9 flex items-center justify-center">
                <img src="images/btu_icon.png" alt="BTU Logo" class="w-full h-full object-contain">
            </div>
            <div>
                <h1 class="text-lg font-bold tracking-tight text-gray-100">BTU AI <span
                        class="text-blue-500 font-medium">Asistan</span></h1>
            </div>
        </div>
    </header>

    <main class="flex-1 relative flex flex-col w-full overflow-hidden">

        <div id="chatContainer" class="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 custom-scrollbar scroll-smooth">

            <div class="flex items-start space-x-4 max-w-4xl mx-auto w-full animate-fade-in mt-4">
                <div
                    class="w-9 h-9 rounded-full bg-[#212121] flex-shrink-0 flex items-center justify-center overflow-hidden p-0.5 border border-white/10">
                    <img src="images/btu_icon.png" alt="BTU" class="w-full h-full object-contain">
                </div>

                <div class="flex flex-col space-y-3 max-w-2xl mt-1">
                    <div class="bg-transparent text-gray-200 text-[15px]">
                        <p class="leading-relaxed">
                            Merhaba! 👋 Ben <strong>Bursa Teknik Üniversitesi</strong> yapay zeka asistanıyım.
                            <br><br>
                            Sana nasıl yardımcı olabilirim? Aşağıdaki konulardan birini seçebilir veya sorunu direkt
                            yazabilirsin.
                        </p>
                    </div>

                    <div class="flex flex-wrap gap-2 mt-2" id="suggestionChips">
                        <button onclick="fillInput('Yaz okulu başvuruları ne zaman?')"
                            class="px-4 py-2 bg-[#2f2f2f] hover:bg-[#3f3f3f] border border-white/5 rounded-xl text-sm text-gray-300 hover:text-white transition-all">📅
                            Akademik Takvim</button>
                        <button onclick="fillInput('Kütüphane çalışma saatleri?')"
                            class="px-4 py-2 bg-[#2f2f2f] hover:bg-[#3f3f3f] border border-white/5 rounded-xl text-sm text-gray-300 hover:text-white transition-all">📚
                            Kütüphane</button>
                        <button onclick="fillInput('Yemekhane menüsü nedir?')"
                            class="px-4 py-2 bg-[#2f2f2f] hover:bg-[#3f3f3f] border border-white/5 rounded-xl text-sm text-gray-300 hover:text-white transition-all">🍔
                            Yemekhane</button>
                    </div>
                </div>
            </div>

        </div>

        <div id="typingIndicator"
            class="hidden absolute bottom-24 left-0 right-0 z-20 pointer-events-none px-4 max-w-4xl mx-auto w-full">
            <div class="flex items-center space-x-2 bg-transparent px-4 py-2 w-fit ml-12">
                <div class="flex space-x-1">
                    <div class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0ms;">
                    </div>
                    <div class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 150ms;">
                    </div>
                    <div class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 300ms;">
                    </div>
                </div>
            </div>
        </div>

    </main>

    <footer class="bg-gradient-to-t from-[#212121] via-[#212121] to-transparent pt-4 pb-6 px-4 z-30 flex-shrink-0">
        <div class="max-w-3xl mx-auto w-full relative">
            <form id="chatForm" class="relative group" onsubmit="return false;">

                <input type="text" id="messageInput"
                    class="w-full bg-[#2f2f2f] border border-white/10 focus:border-gray-500 focus:ring-0 text-gray-100 placeholder-gray-400 pl-6 pr-14 py-4 rounded-3xl outline-none transition-all text-[15px]"
                    placeholder="BTU AI Asistan'a mesaj gönder..." autocomplete="off">

                <button type="submit"
                    class="absolute right-2 top-1/2 transform -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-blue-600 hover:bg-blue-500 text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                    <i class="fa-solid fa-arrow-up text-sm"></i>
                </button>

            </form>
            <p class="text-center text-[11px] text-gray-500 mt-3">
                BTU AI Asistanı hata yapabilir. Lütfen önemli bilgileri teyit ediniz.
            </p>
        </div>
    </footer>

    <script src="script.js"></script>
    <script>
        function fillInput(text) {
            const input = document.getElementById('messageInput');
            input.value = text;
            input.focus();
        }
    </script>
</body>

</html>