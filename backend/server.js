require("dotenv").config();
//console.log("KEY:", process.env.GEMINI_API_KEY);
const express = require("express");
const axios = require("axios");
const cors = require("cors");

const app = express();

app.use(cors());

// 🔥 RAW TEXT INSTEAD OF JSON PARSER
app.use(express.json({ limit: "50mb" }));

// TEST ROUTE
app.get("/", (req, res) => {
  res.send("Server working");
});

// MAIN ROUTE
app.post("/analyze", async (req, res) => {
  try {
    console.log("🔥 ANALYZE HIT");

    const body = req.body;
    console.log("Parsed body:", JSON.stringify(body, null, 2));

    const response = await axios.post(
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
      body,
      {
        headers: {
          "Content-Type": "application/json",
          "x-goog-api-key": process.env.GEMINI_API_KEY
        }
      }
    );

    // ✅ Axios response
    console.log("Gemini response:", JSON.stringify(response.data, null, 2));

    res.json(response.data);

  } catch (error) {
    // 🔥 THIS is how you debug axios errors
    console.error("FULL ERROR:", JSON.stringify(error.response?.data, null, 2));

    res.status(error.response?.status || 500).json(
      error.response?.data || { error: error.message }
    );
  }
});
app.listen(3000, () => {
  console.log("Server running on http://localhost:3000");
});