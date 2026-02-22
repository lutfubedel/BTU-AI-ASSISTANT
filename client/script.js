// Tailwind config ayarları HTML dosyasındaki sınıflarla yönetildiği için buradaki config objesini tamamen kaldırabiliriz, temiz dursun.

document.addEventListener("DOMContentLoaded", () => {
    const chatContainer = document.getElementById("chatContainer");
    const chatForm = document.getElementById("chatForm");
    const messageInput = document.getElementById("messageInput");
    const typingIndicator = document.getElementById("typingIndicator");

    function scrollToBottom() {
        chatContainer.scrollTo({
            top: chatContainer.scrollHeight,
            behavior: 'smooth'
        });
    }

    // --- Message Rendering ---
    function appendUserMessage(message) {
        // İlk etkileşimde öneri butonlarını gizle
        const chips = document.getElementById("suggestionChips");
        if(chips) chips.style.display = 'none';

        const div = document.createElement("div");
        div.className = "flex items-end justify-end space-x-3 animate-slide-in-right mb-6 max-w-4xl mx-auto w-full";
        
        div.innerHTML = `
            <div class="bg-[#2f2f2f] text-gray-100 px-5 py-3.5 rounded-3xl rounded-br-md text-[15px] max-w-[80%] break-words">
                <p class="whitespace-pre-wrap leading-relaxed">${escapeHtml(message)}</p>
            </div>
        `;
        
        chatContainer.appendChild(div);
        scrollToBottom();
    }

    function appendBotMessage(message) {
        const div = document.createElement("div");
        div.className = "flex items-start space-x-4 animate-slide-in-left mb-6 max-w-4xl mx-auto w-full";
        
        const isError = message.startsWith("⚠️") || message.includes("Hata");
        const textClass = isError ? "text-red-400" : "text-gray-200";

        div.innerHTML = `
            <div class="w-9 h-9 rounded-full bg-[#212121] flex-shrink-0 flex items-center justify-center overflow-hidden p-0.5 border border-white/10 mt-1">
                <img src="images/btu_icon.png" alt="BTU" class="w-full h-full object-contain">
            </div>
            <div class="bg-transparent ${textClass} py-2 text-[15px] max-w-[85%] break-words">
                <p class="leading-relaxed whitespace-pre-wrap">${formatLinks(message)}</p>
            </div>
        `;
        chatContainer.appendChild(div);
        scrollToBottom();
    }

    function escapeHtml(text) {
        const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
        return text.replace(/[&<>"']/g, function (m) { return map[m]; });
    }

    // Convert URLs to clickable links
    function formatLinks(text) {
        const urlRegex = /(https?:\/\/[^\s]+)/g;
        return text.replace(urlRegex, function(url) {
            let cleanUrl = url;
            if (cleanUrl.endsWith(')')) cleanUrl = cleanUrl.slice(0, -1);
            return `<a href="${cleanUrl}" target="_blank" class="text-blue-500 hover:text-blue-400 underline decoration-blue-500/30 underline-offset-2 transition-colors">${cleanUrl}</a>`;
        });
    }

    // --- Event Handling ---
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const message = messageInput.value.trim();
        if (!message) return;

        appendUserMessage(message);
        messageInput.value = "";
        messageInput.focus();

        typingIndicator.classList.remove("hidden");
        scrollToBottom();

        try {
            const response = await fetch('http://localhost:5000/chat', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: message }),
            });

            const data = await response.json();

            typingIndicator.classList.add("hidden");

            if (data.status === "success") {
                appendBotMessage(data.reply);
            } else {
                appendBotMessage("⚠️ " + (data.message || "Bilinmeyen bir hata oluştu."));
            }
        } catch (error) {
            console.error("Error:", error);
            typingIndicator.classList.add("hidden");
            appendBotMessage("⚠️ Servise erişilemiyor. Lütfen internet bağlantınızı kontrol edin.");
        }
    });

    messageInput.focus();
});