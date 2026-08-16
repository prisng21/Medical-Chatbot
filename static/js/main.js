$(document).ready(function () {
  symptoms = JSON.parse(symptoms);
  let input = $("#message-text");
  let sendBtn = $("#send");
  let startOverBtn = $("#start-over");
  let dataList = $("#symptoms-list");
  let chat = $("#conversation");

  // ---------- Chat history: replay past sessions ----------
  if (chatHistory && chatHistory.length) {
    $.each(chatHistory, function (i, msg) {
      if (msg.sender === "user") {
        $("#conversation").append(
          `<div class="row message-body"><div class="col-sm-12 message-main-sender"><div class="sender"><div class="message-text">${escapeHtml(msg.text)}</div></div></div></div>`
        );
      } else {
        $("#conversation").append(
          `<div class="row message-body"><div class="col-sm-12 message-main-receiver"><div class="receiver"><div class="message-text">${msg.text}</div></div></div></div>`
        );
      }
    });
    // Scroll to bottom directly: $.fn.scrollToBottom is defined further
    // down, and calling it here would throw and prevent the button
    // handlers below from being attached when chat history exists.
    chat.scrollTop(chat[0].scrollHeight);
  }

  // ---------- Voice output (text-to-speech) ----------
  let ttsOn = localStorage.getItem("meddy_tts") === "1";
  if (ttsOn) $("#tts-toggle").addClass("active");
  $("#tts-toggle").on("click", function () {
    ttsOn = !ttsOn;
    localStorage.setItem("meddy_tts", ttsOn ? "1" : "0");
    $(this).toggleClass("active", ttsOn);
  });

  // Speaks a bot message aloud (HTML is stripped first)
  $.fn.speak = function (text) {
    if (!ttsOn || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    var plain = $("<div>").html(text).text();
    var utter = new SpeechSynthesisUtterance(plain);
    utter.lang = "en-US";
    window.speechSynthesis.speak(utter);
  };

  // ---------- Dark mode ----------
  let darkOn = localStorage.getItem("meddy_dark") === "1";
  if (darkOn) {
    $("body").addClass("dark-mode");
    $("#dark-toggle").addClass("active");
  }
  $("#dark-toggle").on("click", function () {
    darkOn = !darkOn;
    localStorage.setItem("meddy_dark", darkOn ? "1" : "0");
    $("body").toggleClass("dark-mode", darkOn);
    $(this).toggleClass("active", darkOn);
  });

  // ---------- PDF report ----------
  $("#download-report").on("click", function () {
    window.location.href = "/report";
  });

  // ---------- Clear chat history ----------
  $("#clear-history").on("click", function () {
    if (confirm("Clear all chat history?")) {
      $.get("/clear_history", function () {
        location.reload();
      });
    }
  });

  // Handler for any input on the message input field
  input.on("input", function () {
    let insertedValue = $(this).val();
    $("#symptoms-list").empty();

    if (insertedValue.length > 1) {
      ssymptoms = $.fn.getSuggestedSymptoms(insertedValue);
      if (ssymptoms.length === 0) {
        $(".symptoms-list-container ").slideUp();
      } else {
        for (let i = 0; i < ssymptoms.length; i++) {
          var li = document.createElement("li");
          li.textContent = ssymptoms[i];
          dataList.append(li);
        }
        $(".symptoms-list-container ").slideDown();
      }
    } else {
      $(".symptoms-list-container ").slideUp();
    }
  });

  startOverBtn.on("click", function () {
    $.fn.startOver();
  });

  sendBtn.on("click", function () {
    $.fn.handleUserMessage();
  });

  // Quick-reply scenario chips: clicking one sends the whole symptom
  // combination and Meddy answers with the disease recommendation directly
  $("#quick-replies").on("click", ".chip", function () {
    var symptoms = $(this).data("symptoms");
    $.fn.handleScenario(symptoms);
  });

  // Voice typing: converts speech to text and fills the message input
  let voiceBtn = $("#voice-input");
  let isListening = false;
  let recognition = null;

  let SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    // Live transcript while speaking
    recognition.onresult = function (event) {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      input.val(transcript);
    };

    recognition.onstart = function () {
      isListening = true;
      voiceBtn.addClass("listening");
    };

    recognition.onend = function () {
      isListening = false;
      voiceBtn.removeClass("listening");
    };

    recognition.onerror = function (event) {
      console.log("Speech recognition error:", event.error);
      isListening = false;
      voiceBtn.removeClass("listening");
      if (event.error === "not-allowed") {
        alert(
          "Microphone access was denied. Please allow microphone access in your browser and try again."
        );
      }
    };

    voiceBtn.on("click", function () {
      if (isListening) {
        recognition.stop();
      } else {
        input.focus();
        try {
          recognition.start();
        } catch (e) {
          console.log("Could not start speech recognition:", e);
        }
      }
    });
  } else {
    // Browser does not support the Web Speech API (e.g. Firefox)
    voiceBtn.on("click", function () {
      alert(
        "Voice typing is not supported in this browser. Please use Chrome or Edge."
      );
    });
  }

  // Handler for picking one of the suggested symptoms.
  // Use "mousedown" (which fires before the input's blur) and preventDefault
  // so the input never loses focus and the dropdown stays put while the
  // value is filled in. With "click", the blur handler hides the list first
  // and the click never reaches the suggestion.
  dataList.on("mousedown", "li", function (e) {
    e.preventDefault();
    input.val($(this).text());
    $(".symptoms-list-container").slideUp();
  });
  //todo: blur on input - does not work with suggestion item clicks

  input.on("blur", function () {
    $(".symptoms-list-container ").slideUp();
  });

  input.on("keypress", function (e) {
    if (e.which == 13) {
      $.fn.handleUserMessage();
    }
  });

  // Handler function for sending a message
  $.fn.handleUserMessage = function () {
    if (input.val()) {
      $.fn.appendUserMessage();
      $.fn.getPredictedSymptom();
      input.val("");
      $.fn.scrollToBottom();
    }
  };

  $.fn.startOver = function () {
    $.fn.getPredictedSymptom(true);
    $("#conversation").empty();
    const text =
      "Welcome! I'm Medical Chatbot, but you can call me Meddy. What symptoms are you currently experiencing? When you've entered all of your symptoms, please write '<b>Done</b>'. Make sure you enter as much symptoms as possible so the prediction can be as correct as possible.";
    $("#conversation").append(
      `<div class="row message-previous"><div class="col-sm-12 previous"></div></div><div class="row message-body"><div class="col-sm-12 message-main-receiver"><div class="receiver"><div class="message-text">${text}</div></div></div></div>`
    );
    input.val("");
  };

  // Creates the newly sent message element
  $.fn.appendUserMessage = function () {
    var text = input.val();
    $("#conversation").append(
      `<div class="row message-body"><div class="col-sm-12 message-main-sender"><div class="sender"><div class="message-text">${text}</div></div></div></div>`
    );
  };

  // Sends a combination of symptoms at once and shows the disease
  // recommendation directly, without echoing each individual symptom
  $.fn.handleScenario = function (symptoms) {
    if (!symptoms || !symptoms.length) return;
    var label = symptoms.join(", ");
    $("#conversation").append(
      `<div class="row message-body"><div class="col-sm-12 message-main-sender"><div class="sender"><div class="message-text">${label}</div></div></div></div>`
    );
    $.fn.showTyping();
    $.ajax({
      url: "/symptom",
      data: JSON.stringify({ symptoms: symptoms }),
      contentType: "application/json; charset=utf-8",
      dataType: "json",
      type: "POST",
      success: function (response) {
        $.fn.appendBotMessage(response);
      },
      error: function () {
        console.log("Error");
        $.fn.hideTyping();
      },
    });
  };

  $.fn.appendBotMessage = function (text) {
    $.fn.hideTyping();
    $("#conversation").append(
      `<div class="row message-body"><div class="col-sm-12 message-main-receiver"><div class="receiver"><div class="message-text">${text}</div></div></div></div>`
    );
    $.fn.speak(text);
    $.fn.scrollToBottom();
  };

  // Shows an animated "Meddy is typing..." indicator
  $.fn.showTyping = function () {
    if ($(".typing-row").length) return;
    $("#conversation").append(
      `<div class="row message-body typing-row"><div class="col-sm-12 message-main-receiver"><div class="receiver typing"><span></span><span></span><span></span></div></div></div>`
    );
    $.fn.scrollToBottom();
  };

  // Removes the typing indicator
  $.fn.hideTyping = function () {
    $(".typing-row").remove();
  };

  // Smoothly scrolls the chat to the newest message
  $.fn.scrollToBottom = function () {
    chat.stop().animate({ scrollTop: chat[0].scrollHeight }, 250);
  };

  // Retreives prediction to show as bot message
  $.fn.getPredictedSymptom = function (again) {
    var text = input.val();
    if (again) text = "done";

    if (!again) $.fn.showTyping();

    $.ajax({
      url: "/symptom",
      data: JSON.stringify({ sentence: text, start_over: !!again }),
      contentType: "application/json; charset=utf-8",
      dataType: "json",
      type: "POST",
      success: function (response) {
        console.log(response);
        if (!again) $.fn.appendBotMessage(response);
        else $.fn.hideTyping();
      },
      error: function () {
        console.log("Error");
        $.fn.hideTyping();
      },
    });
  };

  $.fn.getSuggestedSymptoms = function (val) {
    let suggestedSymptoms = [];
    $.each(symptoms, function (i, v) {
      if (v.includes(val)) {
        suggestedSymptoms.push(v);
      }
    });
    return suggestedSymptoms.slice(0, 3);
  };

  // Escapes HTML so stored user messages render as plain text
  function escapeHtml(text) {
    return $("<div>").text(text).html();
  }
});
