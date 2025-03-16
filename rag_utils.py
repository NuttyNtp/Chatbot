import os
import json
import time
from typing import List, Dict, Any
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.docstore.document import Document
from web_scraper import TourismScraper
import logging

class RAGManager:
    def __init__(self, model_name: str = "llama2", vector_store_path: str = "vector_store", max_retries: int = 3, timeout: int = 300):
        self.model_name = model_name
        self.vector_store_path = vector_store_path
        self.max_retries = max_retries
        self.timeout = timeout
        self.embeddings = OllamaEmbeddings(model=model_name)
        self.vector_store = None
        self._initialize_vector_store()

    def _initialize_vector_store(self) -> None:
        """Initialize or load the vector store."""
        if os.path.exists(self.vector_store_path):
            try:
                self.vector_store = FAISS.load_local(
                    self.vector_store_path,
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
                logging.info("Successfully loaded existing vector store.")
            except Exception as e:
                logging.error(f"Error loading vector store: {str(e)}")
                self._create_vector_store()
        else:
            self._create_vector_store()

    def _create_vector_store(self) -> None:
        """Create a new vector store from scraped travel data."""
        # Initialize scraper and get travel data
        scraper = TourismScraper()
        destinations = ["bangkok", "phuket", "chiang mai", "ayutthaya", "krabi"]
        documents = []
        logging.info("Starting to create vector store...")
        # Ensure vector store directory exists with proper permissions
        os.makedirs(self.vector_store_path, exist_ok=True)
        # Clear any existing files in the directory
        for file in os.listdir(self.vector_store_path):
            file_path = os.path.join(self.vector_store_path, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                logging.error(f"Error clearing vector store directory: {str(e)}")
                raise
        
        for dest in destinations:
            # Scrape destination data
            results = scraper.scrape_destination(dest)
            for result in results:
                # Create document from scraped data
                content = f"Title: {result['title']}\nDescription: {result['description']}"
                if result['url']:
                    details = scraper.get_destination_details(result['url'])
                    if details.get('content'):
                        content += f"\nDetails: {details['content']}"
                
                documents.append(Document(
                    page_content=content,
                    metadata={'source': result['url'] if result['url'] else 'web_scraping',
                             'title': result['title']}
                ))

        # Check if we have any documents
        if not documents:
            logging.error("No documents were scraped. Cannot create vector store.")
            return

        logging.info(f"Scraped {len(documents)} documents. Processing...")
        # Split documents into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        texts = text_splitter.split_documents(documents)

        if not texts:
            logging.error("No text chunks were created. Cannot create vector store.")
            return

        logging.info(f"Created {len(texts)} text chunks. Generating embeddings...")
        try:
            # Generate embeddings with retry mechanism
            retry_count = 0
            while retry_count < self.max_retries:
                try:
                    embeddings = self.embeddings.embed_documents([text.page_content for text in texts])
                    if embeddings and len(embeddings) > 0:
                        break
                    logging.warning(f"Retry {retry_count + 1}/{self.max_retries}: Empty embeddings received")
                except Exception as e:
                    logging.warning(f"Retry {retry_count + 1}/{self.max_retries}: {str(e)}")
                retry_count += 1
                if retry_count < self.max_retries:
                    time.sleep(2 ** retry_count)  # Exponential backoff
            
            if retry_count >= self.max_retries:
                logging.error("Failed to generate embeddings after maximum retries")
                return
            
            # Create and save vector store
            self.vector_store = FAISS.from_documents(texts, self.embeddings)
            self.vector_store.save_local(self.vector_store_path)
            logging.info("Vector store created and saved successfully.")
        except Exception as e:
            logging.error(f"Error creating vector store: {str(e)}")
            if "Ollama" in str(e):
                logging.error("Please ensure Ollama service is running and accessible.")
            raise

    def get_relevant_context(self, query: str, num_docs: int = 3) -> str:
        """Retrieve relevant context for a given query."""
        if not self.vector_store:
            return ""

        docs = self.vector_store.similarity_search(query, k=num_docs)
        context = "\n\n".join([doc.page_content for doc in docs])
        return context

    def enhance_prompt_with_context(self, query: str, base_prompt: str) -> str:
        """Enhance the base prompt with relevant context."""
        context = self.get_relevant_context(query)
        if not context:
            return base_prompt

        enhanced_prompt = f"""
        Here is some relevant information about the destination:
        {context}

        Using the information above and your knowledge, {base_prompt}
        """
        return enhanced_prompt.strip()