"""
Optimized Template Structure for BibCC

Templates are separated into two categories:
1. JOURNAL_TEMPLATES - Year-agnostic (journals have consistent metadata across years)
2. PROCEEDINGS_TEMPLATES - Year-specific (conferences vary by year: venue, isbn, editor, etc.)

This eliminates redundancy where the same journal was repeated for each year with identical fields.
"""

# Journal templates are keyed by journal name only (no year)
# These fields are constant across all years for a given journal
JOURNAL_TEMPLATES = {
    "ACM Transactions on Knowledge Discovery from Data": {
        "issn": '1556-472X',
        "address": 'New York, NY, USA',
        "publisher": 'Association for Computing Machinery',
    },

    "ACM Transactions on Multimedia Computing, Communications, and Applications": {
        "issn": '1551-6857',
        "address": 'New York, NY, USA',
        "publisher": 'Association for Computing Machinery',
    },

    "Applied Soft Computing": {
        "publisher": 'Elsevier',
        "issn": '1568-4946',
    },

    "Computer Vision and Image Understanding": {
        "publisher": 'Elsevier',
        "issn": '1077-3142',
    },

    "Expert Systems with Applications": {
        "publisher": 'Elsevier',
        "issn": '0957-4174',
    },

    "IEEE Access": {
        "issn": '2169-3536',
        "publisher": 'IEEE',
    },

    "IEEE Internet of Things Journal": {
        "issn": '2327-4662',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Circuits and Systems for Video Technology": {
        "issn": '1558-2205',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Cognitive Communications and Networking": {
        "issn": '2332-7731',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Cybernetics": {
        "issn": '2168-2267',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Geoscience and Remote Sensing": {
        "issn": '1558-0644',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Image Processing": {
        "issn": '1941-0042',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Instrumentation and Measurement": {
        "issn": '1557-9662',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Knowledge and Data Engineering": {
        "publisher": 'IEEE',
        "issn": '1558-2191',
    },

    "IEEE Transactions on Multimedia": {
        "issn": '1941-0077',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Neural Networks and Learning Systems": {
        "issn": '2162-2388',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Pattern Analysis and Machine Intelligence": {
        "issn": '1939-3539',
        "publisher": 'IEEE',
    },

    "IEEE Transactions on Vehicular Technology": {
        "issn": '1939-9359',
        "publisher": 'IEEE',
    },

    "Image and Vision Computing": {
        "publisher": 'Elsevier',
        "issn": '0262-8856',
    },

    "Information Processing \& Management": {
        "publisher": 'Elsevier',
        "issn": '0306-4573',
    },

    "Information Sciences": {
        "publisher": 'Elsevier',
        "issn": '0020-0255',
    },

    "International Journal of Computer Vision": {
        "issn": '1573-1405',
    },

    "International Journal of Fuzzy Systems": {
        "issn": '2199-3211',
    },

    "Knowledge-Based Systems": {
        "publisher": 'Elsevier',
        "issn": '0950-7051',
    },

    "Nature Communications": {
        "issn": '2041-1723',
    },

    "Neural Networks": {
        "publisher": 'Elsevier',
        "issn": '0893-6080',
    },

    "Neurocomputing": {
        "publisher": 'Elsevier',
        "issn": '0925-2312',
    },

    "Pattern Recognition": {
        "publisher": 'Elsevier',
        "issn": '0031-3203',
    },

    "Proceedings of the National Academy of Sciences": {
        "issn": '1091-6490',
        "publisher": 'National Academy of Sciences',
    },

    "Transactions on Machine Learning Research": {
        "issn": '2835-8856',
    },

}


# Proceedings templates are keyed by (venue_name, year) tuple
# These fields vary by year: venue location, isbn, editor, month, etc.
PROCEEDINGS_TEMPLATES = {
    ("2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2025"): {
        "venue": 'Nashville, TN, USA',
        "issn": '2575-7075',
        "isbn": '979-8-3315-4364-8',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2025 IEEE/CVF Winter Conference on Applications of Computer Vision (WACV)", "2025"): {
        "venue": 'Tucson, AZ, USA',
        "issn": '2642-9381',
        "isbn": '979-8-3315-1083-1',
        "publisher": 'IEEE',
        "month": 'February',
    },

    ("Computer Vision -- ECCV 2024", "2025"): {
        "venue": 'Milan, Italy',
        "editor": 'Leonardis, Ale{\\v{s}} and Ricci, Elisa and Roth, Stefan and Russakovsky, Olga and Sattler, Torsten and Varol, G{\\"u}l',
        "issn": '1611-3349',
        "address": 'Cham',
        "publisher": 'Springer Nature Switzerland',
        "series": 'Lecture Notes in Computer Science',
    },

    ("Findings of the Association for Computational Linguistics: ACL 2025", "2025"): {
        "venue": 'Vienna, Austria',
        "publisher": 'Association for Computational Linguistics',
        "month": 'July',
        "isbn": '979-8-89176-256-5',
        "editor": 'Che, Wanxiang  and Nabende, Joyce  and Shutova, Ekaterina  and Pilehvar, Mohammad Taher',
    },

    ("Interspeech 2025", "2025"): {
        "month": 'August',
        "venue": 'Rotterdam, The Netherlands',
        "issn": '2958-1796',
    },

    ("Proceedings of the 33rd ACM International Conference on Multimedia", "2025"): {
        "isbn": '9798400720352',
        "series": "MM '25",
        "address": 'New York, NY, USA',
        "publisher": 'Association for Computing Machinery',
        "venue": 'Dublin, Ireland',
        "month": 'October',
    },

    ("Proceedings of The 3rd Conference on Lifelong Learning Agents", "2025"): {
        "venue": 'Pisa, Italy',
        "editor": 'Lomonaco, Vincenzo and Melacci, Stefano and Tuytelaars, Tinne and Chandar, Sarath and Pascanu, Razvan',
        "series": 'Proceedings of Machine Learning Research',
        "publisher": 'PMLR',
        "month": 'July',
    },

    ("Proceedings of the 42nd International Conference on Machine Learning", "2025"): {
        "venue": 'Vancouver, BC, Canada',
        "editor": 'Singh, Aarti and Fazel, Maryam and Hsu, Daniel and Lacoste-Julien, Simon and Berkenkamp, Felix and Maharaj, Tegan and Wagstaff, Kiri and Zhu, Jerry',
        "series": 'Proceedings of Machine Learning Research',
        "publisher": 'PMLR',
        "month": 'July',
        "day": '13--19',
    },

    ("Proceedings of the AAAI Conference on Artificial Intelligence", "2025"): {
        "isbn": '978-1-57735-897-8',
        "venue": 'Philadelphia, Pennsylvania, USA',
        "issn": '2374-3468',
        "address": 'Washington, DC, USA',
        "publisher": 'AAAI Press',
        "month": 'April',
    },

    ("Proceedings of the ACM on Web Conference 2025", "2025"): {
        "venue": 'Sydney, NSW, Australia',
        "publisher": 'Association for Computing Machinery',
        "isbn": '9798400712746',
        "series": "WWW '25",
        "address": 'New York, NY, USA',
    },

    ("Proceedings of the Eighteenth ACM International Conference on Web Search and Data Mining", "2025"): {
        "isbn": '979-8-4007-1329-3',
        "series": "WSDM '25",
        "address": 'New York, NY, USA',
        "publisher": 'Association for Computing Machinery',
        "venue": 'Hannover, Germany',
        "month": 'March',
    },

    ("Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV)", "2025"): {
        "month": 'October',
    },

    ("Proceedings of the Thirty-Fourth International Joint Conference on Artificial Intelligence, {IJCAI-25}", "2025"): {
        "venue": 'Montreal, Canada',
        "editor": 'James Kwok',
        "isbn": '978-1-956792-06-5',
        "publisher": 'International Joint Conferences on Artificial Intelligence Organization',
        "month": 'August',
    },

    ("The Thirteenth International Conference on Learning Representations", "2025"): {
        "venue": 'Singapore',
    },

    ("The Thirty-ninth Annual Conference on Neural Information Processing Systems", "2025"): {
    },

    ("2024 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2024"): {
        "venue": 'Seattle, WA, USA',
        "issn": '2575-7075',
        "isbn": '979-8-3503-5300-6',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2024 IEEE/CVF Winter Conference on Applications of Computer Vision (WACV)", "2024"): {
        "venue": 'Waikoloa, HI, USA',
        "issn": '2642-9381',
        "isbn": '979-8-3503-1892-0',
        "publisher": 'IEEE',
        "month": 'January',
    },

    ("Advanced Intelligent Computing Technology and Applications", "2024"): {
        "month": 'August',
        "venue": 'Tianjin, China',
        "address": 'Singapore',
        "editor": 'Huang, De-Shuang and Zhang, Xiankun and Zhang, Chuanlei',
        "isbn": '978-981-97-5675-9',
        "publisher": 'Springer Nature Singapore',
    },

    ("Advances in Neural Information Processing Systems", "2024"): {
        "venue": 'Vancouver, BC, Canada',
        "editor": 'A. Globerson and L. Mackey and D. Belgrave and A. Fan and U. Paquet and J. Tomczak and C. Zhang',
        "isbn": '979-8-3313-1438-5',
        "address": 'Red Hook, NY, USA',
        "publisher": 'Curran Associates, Inc.',
        "month": 'December',
    },

    ("Medical Image Computing and Computer Assisted Intervention -- MICCAI 2024", "2024"): {
        "month": 'October',
        "venue": 'Marrakesh, Morocco',
        "editor": 'Linguraru, Marius George and Dou, Qi and Feragen, Aasa and Giannarou, Stamatia and Glocker, Ben and Lekadir, Karim and Schnabel, Julia A.',
        "isbn": '978-3-031-72117-5',
        "address": 'Cham',
        "publisher": 'Springer Nature Switzerland',
    },

    ("Proceedings of the 21st ACM Conference on Embedded Networked Sensor Systems", "2024"): {
        "month": 'November',
        "venue": 'Istanbul, Turkiye',
        "isbn": '979-8-4007-0414-7',
        "series": "SenSys '23",
        "address": 'New York, NY, USA',
        "publisher": 'Association for Computing Machinery',
    },

    ("Proceedings of the 32nd ACM International Conference on Multimedia", "2024"): {
        "venue": 'Melbourne, VIC, Australia',
        "address": 'New York, NY, USA',
        "publisher": 'Association for Computing Machinery',
        "isbn": '9798400706868',
        "series": "MM '24",
    },

    ("Proceedings of the 41st International Conference on Machine Learning", "2024"): {
        "venue": 'Vienna, Austria',
        "editor": 'Salakhutdinov, Ruslan and Kolter, Zico and Heller, Katherine and Weller, Adrian and Oliver, Nuria and Scarlett, Jonathan and Berkenkamp, Felix',
        "series": 'Proceedings of Machine Learning Research',
        "publisher": 'PMLR',
        "month": 'July',
        "day": '21--27',
    },

    ("Proceedings of the AAAI Conference on Artificial Intelligence", "2024"): {
        "venue": 'Vancouver, BC, Canada',
        "issn": '2374-3468',
        "isbn": '978-1-57735-887-9',
        "address": 'Washington, DC, USA',
        "publisher": 'AAAI Press',
        "month": 'March',
    },

    ("Proceedings of the Thirty-Third International Joint Conference on Artificial Intelligence, {IJCAI-24}", "2024"): {
        "venue": 'Jeju, Korea',
        "isbn": '978-1-939133-37-9',
        "editor": 'Kate Larson',
        "publisher": 'International Joint Conferences on Artificial Intelligence Organization',
        "month": 'August',
    },

    ("The Twelfth International Conference on Learning Representations", "2024"): {
        "month": 'May',
        "venue": 'Vienna, Austria',
    },

    ("2023 IEEE International Conference on Systems, Man, and Cybernetics (SMC)", "2023"): {
        "venue": 'Honolulu, Oahu, HI, USA',
        "issn": '2577-1655',
        "isbn": '979-8-3503-3702-0',
        "publisher": 'IEEE',
        "month": 'October',
    },

    ("2023 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2023"): {
        "venue": 'Vancouver, BC, Canada',
        "issn": '2575-7075',
        "isbn": '979-8-3503-0129-8',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2023 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)", "2023"): {
        "venue": 'Vancouver, BC, Canada',
        "issn": '2160-7516',
        "isbn": '979-8-3503-0249-3',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2023 IEEE/CVF International Conference on Computer Vision (ICCV)", "2023"): {
        "venue": 'Paris, France',
        "issn": '2380-7504',
        "isbn": '979-8-3503-0718-4',
        "publisher": 'IEEE',
        "month": 'October',
    },

    ("2023 IEEE/CVF International Conference on Computer Vision Workshops (ICCVW)", "2023"): {
        "venue": 'Paris, France',
        "issn": '2473-9944',
        "isbn": '979-8-3503-0744-3',
        "publisher": 'IEEE',
        "month": 'October',
    },

    ("2023 IEEE/CVF Winter Conference on Applications of Computer Vision (WACV)", "2023"): {
        "venue": 'Waikoloa, HI, USA',
        "issn": '2642-9381',
        "isbn": '978-1-6654-9346-8',
        "publisher": 'IEEE',
        "month": 'January',
    },

    ("Advances in Neural Information Processing Systems", "2023"): {
        "isbn": '978-1-7138-9992-1',
        "venue": 'New Orleans, LA, USA',
        "editor": 'A. Oh and T. Naumann and A. Globerson and K. Saenko and M. Hardt and S. Levine',
        "address": 'Red Hook, NY, USA',
        "publisher": 'Curran Associates, Inc.',
        "month": 'December',
    },

    ("Proceedings of The 2nd Conference on Lifelong Learning Agents", "2023"): {
        "venue": 'Montreal, QC, Canada',
        "editor": 'Chandar, Sarath and Pascanu, Razvan and Sedghi, Hanie and Precup, Doina',
        "series": 'Proceedings of Machine Learning Research',
        "publisher": 'PMLR',
        "month": 'August',
    },

    ("Proceedings of the 40th International Conference on Machine Learning", "2023"): {
        "venue": 'Honolulu, HI, USA',
        "editor": 'Krause, Andreas and Brunskill, Emma and Cho, Kyunghyun and Engelhardt, Barbara and Sabato, Sivan and Scarlett, Jonathan',
        "series": 'Proceedings of Machine Learning Research',
        "publisher": 'PMLR',
        "day": '23--29',
        "month": 'July',
    },

    ("Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)", "2023"): {
        "venue": 'Toronto, ON, Canada',
        "editor": 'Rogers, Anna and Boyd-Graber, Jordan and Okazaki, Naoaki',
        "publisher": 'Association for Computational Linguistics',
        "month": 'July',
    },

    ("The Eleventh International Conference on Learning Representations", "2023"): {
        "venue": 'Kigali, Rwanda',
        "month": 'May',
    },

    ("2022 IEEE International Conference on Image Processing (ICIP)", "2022"): {
        "venue": 'Bordeaux, France',
        "issn": '2381-8549',
        "isbn": '978-1-6654-9620-9',
        "publisher": 'IEEE',
        "month": 'October',
    },

    ("2022 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2022"): {
        "venue": 'New Orleans, LA, USA',
        "issn": '2575-7075',
        "isbn": '978-1-6654-6946-3',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2022 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)", "2022"): {
        "venue": 'New Orleans, LA, USA',
        "issn": '2160-7516',
        "isbn": '978-1-6654-8739-9',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2022 International Joint Conference on Neural Networks (IJCNN)", "2022"): {
        "venue": 'Padua, Italy',
        "issn": '2161-4407',
        "isbn": '978-1-7281-8671-9',
        "publisher": 'IEEE',
        "month": 'July',
    },

    ("Advances in Neural Information Processing Systems", "2022"): {
        "month": 'November',
        "isbn": '978-1-7138-7108-8',
        "venue": 'New Orleans, LA, USA',
        "editor": 'S. Koyejo and S. Mohamed and A. Agarwal and D. Belgrave and K. Cho and A. Oh',
        "address": 'Red Hook, NY, USA',
        "publisher": 'Curran Associates, Inc.',
    },

    ("Computer Vision -- ECCV 2022", "2022"): {
        "venue": 'Tel Aviv, Israel',
        "editor": "Avidan, Shai and Brostow, Gabriel and Ciss{\\'e}, Moustapha and Farinella, Giovanni Maria and Hassner, Tal",
        "address": 'Cham',
        "publisher": 'Springer Nature Switzerland',
        "month": 'October',
        "series": 'Lecture Notes in Computer Science',
        "issn": '1611-3349',
    },

    ("Proceedings of the AAAI Conference on Artificial Intelligence", "2022"): {
        "publisher": 'AAAI Press',
        "month": 'June',
        "isbn": '978-1-57735-876-3',
        "issn": '2374-3468',
        "address": 'Palo Alto, California, USA',
    },

    ("2021 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2021"): {
        "venue": 'Nashville, TN, USA',
        "issn": '2575-7075',
        "isbn": '978-1-6654-4509-2',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2021 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)", "2021"): {
        "venue": 'Nashville, TN, USA',
        "issn": '2160-7516',
        "isbn": '978-1-6654-4899-4',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2021 IEEE/CVF International Conference on Computer Vision (ICCV)", "2021"): {
        "venue": 'Montreal, QC, Canada',
        "publisher": 'IEEE',
        "month": 'October',
        "isbn": '978-1-6654-2812-5',
        "issn": '2380-7504',
    },

    ("Advances in Neural Information Processing Systems", "2021"): {
        "editor": 'M. Ranzato and A. Beygelzimer and Y. Dauphin and P.S. Liang and J. Wortman Vaughan',
        "isbn": '978-1-7138-4539-3',
        "address": 'Red Hook, NY, USA',
        "publisher": 'Curran Associates, Inc.',
        "month": 'December',
    },

    ("Artificial Neural Networks and Machine Learning -- ICANN 2021", "2021"): {
        "month": 'September',
        "venue": 'Bratislava, Slovakia',
        "editor": 'Farka{\\v{s}}, Igor and Masulli, Paolo and Otte, Sebastian and Wermter, Stefan',
        "isbn": '978-3-030-86340-1',
        "address": 'Cham',
        "publisher": 'Springer International Publishing',
    },

    ("International Conference on Learning Representations", "2021"): {
        "month": 'May',
        "venue": 'Vienna, Austria',
    },

    ("Proceedings of the 2021 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies", "2021"): {
        "venue": 'Online',
        "editor": 'Toutanova, Kristina and Rumshisky, Anna and Zettlemoyer, Luke and Hakkani-Tur, Dilek and Beltagy, Iz and Bethard, Steven and Cotterell, Ryan and Chakraborty, Tanmoy and Zhou, Yichao',
        "publisher": 'Association for Computational Linguistics',
        "month": 'June',
    },

    ("Proceedings of the AAAI Conference on Artificial Intelligence", "2021"): {
        "venue": 'Stockholmsmässan, Stockholm, Sweden',
        "publisher": 'AAAI Press',
        "month": 'May',
        "isbn": '978-1-57735-866-4',
        "issn": '2374-3468',
        "series": 'Proceedings of Machine Learning Research',
        "address": 'Palo Alto, California, USA',
    },

    ("2020 IEEE Winter Conference on Applications of Computer Vision (WACV)", "2020"): {
        "venue": 'Snowmass, CO, USA',
        "publisher": 'IEEE',
        "month": 'March',
        "isbn": '978-1-7281-6553-0',
        "issn": '2642-9381',
    },

    ("2020 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2020"): {
        "venue": 'Seattle, WA, USA',
        "publisher": 'IEEE',
        "month": 'June',
        "isbn": '978-1-7281-7168-5',
        "issn": '2575-7075',
    },

    ("2020 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)", "2020"): {
        "venue": 'Seattle, WA, USA',
        "issn": '2160-7516',
        "isbn": '978-1-7281-9360-1',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("Computer Vision -- ECCV 2020", "2020"): {
        "venue": 'Glasgow, UK',
        "publisher": 'Springer International Publishing',
        "month": 'August',
        "issn": '1611-3349',
        "editor": 'Vedaldi, Andrea and Bischof, Horst and Brox, Thomas and Frahm, Jan-Michael',
        "series": 'Lecture Notes in Computer Science',
        "address": 'Cham',
    },

    ("2019 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2019"): {
        "venue": 'Long Beach, CA, USA',
        "issn": '2575-7075',
        "isbn": '978-1-7281-3293-8',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("2019 IEEE/CVF International Conference on Computer Vision (ICCV)", "2019"): {
        "venue": 'Seoul, Korea (South)',
        "issn": '2380-7504',
        "isbn": '978-1-7281-4803-8',
        "publisher": 'IEEE',
        "month": 'October',
    },

    ("International Conference on Learning Representations", "2019"): {
        "venue": 'New Orleans, LA, USA',
        "month": 'May',
    },

    ("Proceedings of the 25th ACM SIGKDD International Conference on Knowledge Discovery \& Data Mining", "2019"): {
        "venue": 'Anchorage, AK, USA',
        "publisher": 'Association for Computing Machinery',
        "month": 'August',
        "isbn": '978-1-4503-6201-6',
        "series": "KDD '19",
        "address": 'New York, NY, USA',
    },

    ("Proceedings of the 36th International Conference on Machine Learning", "2019"): {
        "venue": 'Long Beach, CA, USA',
        "publisher": 'PMLR',
        "month": 'June',
        "editor": 'Chaudhuri, Kamalika and Salakhutdinov, Ruslan',
        "series": 'Proceedings of Machine Learning Research',
    },

    ("2018 IEEE/CVF Conference on Computer Vision and Pattern Recognition", "2018"): {
        "venue": 'Salt Lake City, UT, USA',
        "issn": '2575-7075',
        "isbn": '978-1-5386-6420-9',
        "publisher": 'IEEE',
        "month": 'June',
    },

    ("Advances in Neural Information Processing Systems", "2018"): {
        "venue": 'Montreal, QC, Canada',
        "publisher": 'Curran Associates, Inc.',
        "month": 'December',
        "isbn": '978-1-5108-8447-2',
        "editor": 'S. Bengio and H. Wallach and H. Larochelle and K. Grauman and N. Cesa-Bianchi and R. Garnett',
        "address": 'Red Hook, NY, USA',
    },

    ("British Machine Vision Conference (BMVC)", "2018"): {
        "month": 'September',
        "venue": 'Northumbria University, Newcastle, UK',
    },

    ("Computer Vision -- ECCV 2018", "2018"): {
        "venue": 'Munich, Germany',
        "editor": 'Ferrari, Vittorio and Hebert, Martial and Sminchisescu, Cristian and Weiss, Yair',
        "address": 'Cham',
        "publisher": 'Springer International Publishing',
        "month": 'September',
        "issn": '1611-3349',
        "series": 'Lecture Notes in Computer Science',
    },

    ("International Conference on Learning Representations", "2018"): {
        "venue": 'Vancouver, BC, Canada',
    },

    ("Proceedings of the 35th International Conference on Machine Learning", "2018"): {
        "venue": 'Stockholmsmässan, Stockholm Sweden',
        "publisher": 'PMLR',
        "month": 'July',
        "editor": 'Dy, Jennifer and Krause, Andreas',
        "series": 'Proceedings of Machine Learning Research',
    },

    ("Advances in Neural Information Processing Systems", "2017"): {
        "isbn": '978-1-5108-6096-4',
        "venue": 'Long Beach, CA, USA',
        "editor": 'I. Guyon and U. Von Luxburg and S. Bengio and H. Wallach and R. Fergus and S. Vishwanathan and R. Garnett',
        "address": 'Red Hook, NY, USA',
        "publisher": 'Curran Associates, Inc.',
        "month": 'December',
    },

    ("Proceedings of the 34th International Conference on Machine Learning", "2017"): {
        "venue": 'Sydney, Australia',
        "editor": 'Precup, Doina and Teh, Yee Whye',
        "series": 'Proceedings of Machine Learning Research',
        "publisher": 'PMLR',
        "day": '06--11',
        "month": 'August',
    },

    ("Advances in Neural Information Processing Systems", "2016"): {
        "venue": 'Barcelona, Spain',
        "month": 'December',
    },

    ("Computer Vision -- ECCV 2016", "2016"): {
        "venue": 'Amsterdam, Netherlands',
        "editor": 'Leibe, Bastian and Matas, Jiri and Sebe, Nicu and Welling, Max',
        "address": 'Cham',
        "publisher": 'Springer International Publishing',
        "month": 'October',
        "issn": '1611-3349',
        "series": 'Lecture Notes in Computer Science',
    },

}
