#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;
use Image::Magick;
use PDF::API2;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root);
my $logd_in = 0;
my $id;
my $full_user = 0;

my %session;
my $update_session = 0;

my @grc_classes = ();

my $pdf_mode = 0;
my %grading = ();

my %core_fonts = (
"Times-Roman" => 1,
"Times-Bold" => 1,
"Times-Italic" => 1,
"Times-BoldItalic" => 1,

"Helvetica" => 1,
"Helvetica-Bold" => 1,

"Courier" => 1,
"Times-Bold" => 1,
"Courier-Oblique" => 1,
"Times-BoldOblique" => 1,

"Symbol" => 1,
"ZapfDingbats" => 1);

my ($page,$pdf,$filename) = (undef, undef, undef);
my ($llx,$urx, $lly, $ury) = (0,595,842,0);
my %data = ();
my $auto_resize = 1;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	#logged in 
	if (exists $session{"id"}) {
		$id = $session{"id"};
		#privileges set
		if (exists $session{"privileges"}) {
			my $priv_str = $session{"privileges"};
			my $spc = " ";
			$priv_str =~ s/\+/$spc/g;
			$priv_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			if ($priv_str eq "all") { 
				$logd_in++;
				$full_user++;
			}
			else {
				if (exists $session{"token_expiry"} and $session{"token_expiry"} =~ /^\d+$/) {
					if ($session{"token_expiry"} > time) {
						$logd_in++;
						my @privs = split/,/,$priv_str;
						my $cntr = 0;
						foreach (@privs) {	
							if ($_ =~ m!^GRC\(([^\)]+)\)$!) {	
								push @grc_classes, $1;
							}
						}
					}
				}
			}
		}
	}
}

unless ($logd_in) {
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /login.html?cont=/cgi-bin/genreportcards.cgi\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
   	my $res = 
qq{
<html>
<head>
<title>Spanj: Exam Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/genreportcards.cgi">/login.html?cont=/cgi-bin/genreportcards.cgi</a>. If you were not, <a href="/cgi-bin/genreportcards.cgi">Click Here</a> 
</body>
</html>
};

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
	exit 0;
}

my $post_mode = 0;
my %auth_params;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	$post_mode++;
	my $str = "";

	while (<STDIN>) {
		$str .= $_;
	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
	my @auth_req = split/&/,$str;
	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
		}
	}
}

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/genreportcards.cgi">Generate Report Cards</a>
	<hr> 
};

my $con;
my $content = "";

if (@grc_classes or $full_user) {
	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
	#read some config information
	#exam,classes,subjects
	my $current_exam = "";
	my @valid_classes = ();
	my @valid_subjects = ();		
	#pre-load the blank grade, useful 
	#when get_grade returns a blank
	my %remarks = ("" => "");
	my $show_remarks = 0;
	my $show_pictures = 0;
	my $show_grade = 0;
	my $show_admission_data = 1;
	my $show_dorm = 0;
	my $show_input_by = 0;
	
	my $prep_stmt = $con->prepare("SELECT id,value FROM vars WHERE id='1-exam' OR id='1-classes' OR id='1-subjects' OR id='1-grading' OR id='1-remarks' OR id='1-show remarks' OR id='1-show pictures' OR id='1-show grade' OR id='1-show admission data' OR id='1-show dorm' OR id='1-show input by' LIMIT 11");

	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {
				if ($rslts[0] eq "1-exam") {
					$current_exam = $rslts[1];
					my $current_year = (localtime)[5] + 1900;
					if ($current_exam !~ /$current_year/) {
						$current_exam .= "($current_year)";
					}
				}
				elsif ($rslts[0] eq "1-classes") {
					my $classes = $rslts[1];
					@valid_classes = split/,/,$classes;	
				}
				elsif ($rslts[0] eq "1-subjects") {
					my $subjects = $rslts[1];
					@valid_subjects = split/,/,$subjects;	
				}
				elsif ($rslts[0] eq "1-grading") {
					my $grading_str = $rslts[1];
					my @grading_bts = split/,/,$grading_str;
					foreach (@grading_bts) {
						if ($_ =~ /^([^:]+):\s*(.+)$/) {
							my ($condition,$grade) = ($1,$2);
							#greater than (>|>=)
							#set min value
							if ($condition =~ /^\s*>\s*(\d+)$/) {
								${$grading{$grade}}{"min"} = $1
							}
							elsif ($condition =~ /^\s*>=\s*(\d+)$/) {
								my $min = $1;
								$min--;
								${$grading{$grade}}{"min"} = $min;
							}
							#less than (<|<=)
							#set max value of condition
							elsif ($condition =~ /^\s*<\s*(\d+)$/) {
								${$grading{$grade}}{"max"} = $1
							}
							elsif ($condition =~ /^\s*<=\s*(\d+)$/) {
								my $max = $1;
								$max++;
								${$grading{$grade}}{"max"} = $max;
							}
							#handle ranges
							#x-y
							elsif ($condition =~ /^\s*(\d+)\s*\-\s*(\d+)$/) {
								my ($min,$max) = ($1,$2);
								#don't be hard on users
								#reverse $min & $max if
								#they've been 'jumbled'
								if ($max < $min) {
									my $tmp = $max;
									$max = $min;
									$min = $tmp;
								}
								${$grading{$grade}}{"min"} = $min;
								${$grading{$grade}}{"max"} = $max;
							}
							#handle equality (=)
							#set eqs
							elsif ($condition =~ /^\s*=\s*(\d+)$/) {
								${$grading{$grade}}{"eq"} = $1
							}
						}
					}
				}
				elsif ($rslts[0] eq "1-remarks") {
					my $remarks_str = $rslts[1];
					my @remarks_bts = split/,/,$remarks_str;
					foreach (@remarks_bts) {
						if ($_ =~ /^([^:]+):\s*(.+)/) {
							my ($grade,$remark) = ($1,$2);
							$remarks{$grade} = $remark;	
						}
					}
				}

				elsif ($rslts[0] eq "1-show remarks") {
					if (lc($rslts[1]) eq "yes") {
						$show_remarks = 1;
					}
				}

				elsif ($rslts[0] eq "1-show grade") {
					if (lc($rslts[1]) eq "yes") {
						$show_grade = 1;
					}
				}


				elsif ($rslts[0] eq "1-show dorm") {
					if (lc($rslts[1]) eq "yes") {
						$show_dorm = 1;
					}
				}

				elsif ($rslts[0] eq "1-show pictures") {
					if (lc($rslts[1]) eq "yes") {
						$show_pictures = 1;
					}
				}

				elsif ($rslts[0] eq "1-show admission data") {
					if (lc($rslts[1]) eq "no") {
						$show_admission_data = 0;
					}
				}

				elsif ($rslts[0] eq "1-show input by") {
					if (lc($rslts[1]) eq "yes") {
						$show_input_by = 1;
					}
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: $prep_stmt->errstr$/";
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: $prep_stmt->errstr$/";
	}
	
	if (keys %grading) {
		$show_grade++;
	}

	my @authd_classes = ();

	if ($full_user) {
		@authd_classes = @valid_classes;
	}

	else {
		#why did I not just @authd_classes = @grc_classes?
		#well, I'm paranoid: I don't trust @grc_classes
		#plus, I want to get the case right so future REs don't
		#have to be /i modified
		for my $valid_class (@valid_classes) {
			A: for my $grc_class (@grc_classes) {
				if ( lc($valid_class) eq lc($grc_class) ) {
					push @authd_classes, $valid_class;
					last A;
				}
			}
		}
	}

	if ($post_mode) {
		#check confirm code
		if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"}) {
			
			#verify authority to edit this class
			my $fail = 0;
			my $err_str = "";
				
			if (exists $auth_params{"download"}) {
				$pdf_mode = 1;
			}

			my $exam = undef; 
			my %included_exams = ();
			my %included_exams_age = ();

			if (exists $auth_params{"exam"}) { 
				$exam = $auth_params{"exam"};
			}
			else {
				$fail = 1;
				$err_str = "Sorry you did not select any exam.";
			}
			my %classes;
	
			my $cntr = 0;
			my $inc_cnt = 0;

			B: foreach (keys %auth_params) {
				if ($_ =~ /^class_/) {
					my $class = $auth_params{$_};
					my $match = 0;
					C: foreach (@authd_classes) {
						if (lc($_) eq lc($class)) {
							$class = $_;
							$match++;
							last C;
						}
					}
					unless ($match) {
						$fail = 1;
						$err_str = "Sorry, you are not authorized to edit one or more of the classes selected.";
						last B;
					}
					$classes{lc($class)}++;
					$cntr++;
				}
	
				elsif ($_ =~ /^include_\d+$/) {	
					my $included_exam = $auth_params{$_};
					if ($included_exam ne $exam) {
						$included_exams{$included_exam}++;
						$included_exams_age{$included_exam} = ++$inc_cnt;
					}
				}
			}
	
			if ($pdf_mode) {
				
				my $classes = join(',', keys %classes);
				$filename = "report_cards-" . $exam . "_" . $classes;
				$filename =~ s/\s+/_/g;

				$pdf = PDF::API2->new(-file => "${doc_root}reportcards/$filename.pdf");				
				$pdf->info("Author" => $id, "Title" => "$exam report cards for $classes", "Subject" => "Report Cards");	
			}
			if ($cntr == 0) {
				$fail = 1;
				$err_str = "Sorry, you did not select any class.";	
			}
			if ($fail) {
				$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>$err_str</em>
</body>
</html>
};
			}
			else {
				#valid request- OK confirmation code, authorized class
				my %possib_start_yrs = ();

				my $current_year = (localtime)[5] + 1900;
				if ($exam =~ /\D*(\d{4,})\D*/) {
					$current_year = $1;
				}

				for my $class_name (keys %classes) {	
					my ($class_year,$start_year) = (-1,-1);
					if ($class_name =~ /(\d+)/) {
						$class_year = $1;	
						$start_year = 1 + ($current_year - $class_year);
						$possib_start_yrs{$start_year}++;
					}
				}
				my %stud_rolls;
				my $matched_rolls = 0;

				my @start_yr_where_clause_bts = ();

				foreach (keys %possib_start_yrs) {
					push @start_yr_where_clause_bts, "start_year=?";
				}
				my $start_yr_where_clause = join (' OR ', @start_yr_where_clause_bts);

				my $prep_stmt3 = $con->prepare("SELECT table_name,class,grad_year,size,start_year FROM student_rolls WHERE $start_yr_where_clause");
				if ($prep_stmt3) {
					my $rc = $prep_stmt3->execute(keys %possib_start_yrs);
					if ($rc) {
						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							my $class_yr_then = 1 + ($current_year - $rslts[4]);
							$rslts[1] =~ s/\d+/$class_yr_then/;
							$stud_rolls{$rslts[0]} = {"class" => $rslts[1], "grad_year" => $rslts[2], "size" => $rslts[3]};
							$matched_rolls++;
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM student_rolls statement: $prep_stmt3->errstr$/";
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM student_rolls statement: $prep_stmt3->errstr$/";
				}
				if ($matched_rolls) {
					my @where_clause_bts = ();
					foreach (keys %stud_rolls) {
						push @where_clause_bts, "roll=?";
					}
					my $where_clause = join(' OR ', @where_clause_bts);

					my $exam_where_clause = qq{exam_name=?};

					if (keys %included_exams) {
						my @exam_clause_bts = ();
						push @exam_clause_bts, "exam_name=?";
						foreach (keys %included_exams) {
							push @exam_clause_bts, "exam_name=?";
						}
						$exam_where_clause = join(" OR ", @exam_clause_bts);
					}

					my %marksheet_list;

			      		my $prep_stmt4 = $con->prepare("SELECT table_name,roll,exam_name,subject,time FROM marksheets WHERE ($exam_where_clause) AND ($where_clause)");
					if ($prep_stmt4) {

						my @exec_params = keys %stud_rolls;
						unshift @exec_params,$exam,keys %included_exams;

						my $rc = $prep_stmt4->execute(@exec_params);
						if ($rc) {
							while (my @rslts = $prep_stmt4->fetchrow_array()) {
								${$stud_rolls{$rslts[1]}}{"marksheet_" . $rslts[2] . "_" . $rslts[3]} = $rslts[0];
								if (keys %included_exams) {	
									if ($rslts[4] > $included_exams_age{$rslts[2]}) {
										$included_exams_age{$rslts[2]} = $rslts[4];
									}
								}
								$marksheet_list{$rslts[0]} = $rslts[2] . "_" . $rslts[3];	
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM student_rolls statement: $prep_stmt4->errstr$/";
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM student_rolls statement: $prep_stmt4->errstr$/";
					}

					my %teachers;
	
					if (keys %marksheet_list) {
						my @where_clause_bts = ();
						foreach (keys %marksheet_list) {
							push @where_clause_bts, "marksheet=?";
						}
						my $where_clause = join(" OR ", @where_clause_bts);
						
						my $prep_stmt6 = $con->prepare("SELECT marksheet,teacher FROM edit_marksheet_log WHERE $where_clause");
						
						if ($prep_stmt6) {
							my $rc = $prep_stmt6->execute(keys %marksheet_list);
							if ($rc) {
								while (my @rslts = $prep_stmt6->fetchrow_array()) {	
									$teachers{$marksheet_list{$rslts[0]}} = $rslts[1];
								}
							}
							else {
								print STDERR "Could not SELECT FROM edit_marksheet_log: $prep_stmt6->errstr$/";
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM edit_marksheet_log: $prep_stmt6->errstr$/";
						}
					}

					my $cnt = 0;
					foreach (keys %teachers) {	
						$cnt++;
					}
					$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
};

					#read student rolls
					#save adm,marks at admission & subjects
					my %student_data;

					for my $roll (keys %stud_rolls) {
						my $class = ${$stud_rolls{$roll}}{"class"};

						my $prep_stmt5 = $con->prepare("SELECT adm,s_name,o_names,marks_at_adm,subjects,clubs_societies,sports_games,responsibilities,house_dorm FROM `$roll`");
						if ($prep_stmt5) {

							my $rc = $prep_stmt5->execute();
							if ($rc) {
								while (my @rslts = $prep_stmt5->fetchrow_array()) {
									my ($adm,$s_name,$o_names,$marks_at_adm,$subjects,$clubs_societies,$sports_games,$responsibilities,$house_dorm) = @rslts;
									if (not defined($marks_at_adm) or $marks_at_adm eq "") {
										$marks_at_adm = -1;
									}
									 
									$student_data{$adm} = 
									{
									"name" => $s_name . " " . $o_names,
									"marks_at_adm" => $marks_at_adm,	
									"roll" => $roll,
									"total" => 0,
									"subject_count" => 0,
									"avg" => -1,
									"admission_rank" => "N/A",
									"class_rank" => 1,
									"overall_rank" => 1,
									"class" => $class,
									"clubs_societies" => $clubs_societies,
									"sports_games" => $sports_games,
									"responsibilities" => $responsibilities,
									"house_dorm" => $house_dorm
									};
									#preset the values of subjects to N/A
									my @subjects_list = split/,/, $subjects;
									for my $exam_n ($exam, keys %included_exams) {
										foreach (@subjects_list) {	
											${$student_data{$adm}}{"subject_${exam_n}_${_}"} = "N/A";
										}
									}
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM student_roll statement: $prep_stmt5->errstr$/";
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM student_roll statement: $prep_stmt5->errstr$/";
						}
					}
						
					#read the marksheets in DB:-
					#for each marksheet, update student_data	
					#in the switch from F2-F3 the student's, for instance,
					#'subjects' records are changed
					#RULE: assume subjects can be removed but not
					#added. Therefore, any missing records in the 
					#{"subjects"} field are N/A
					#any additional values however, are allowed
						
					for my $stud_roll (keys %stud_rolls) {
						my %recs = %{$stud_rolls{$stud_roll}};		
						for my $rec_key (keys %recs) {
							my $prep_stmt5;
							if ($rec_key =~ /^marksheet_([^_]+)_(.+)$/) {
								my $n_exam = $1;
								my $subject = $2;

								my $marksheet = $recs{$rec_key};
								
								$prep_stmt5 = $con->prepare("SELECT adm,marks FROM `$marksheet`");
								my %marksheet_data = ();
								if ($prep_stmt5) {
								
									my $rc = $prep_stmt5->execute();
									if ($rc) {
										while (my @rslts = $prep_stmt5->fetchrow_array()) {
											$marksheet_data{$rslts[0]} = $rslts[1];
										}
									}
									else {
										print STDERR "Could not execute SELECT FROM marksheet statement: $prep_stmt5->errstr$/";
									}
								}
								else {
									print STDERR "Could not prepare SELECT FROM marksheet statement: $prep_stmt5->errstr$/";
								}
								for my $stud_adm (keys %marksheet_data) {
									
 									${$student_data{$stud_adm}}{"subject_${n_exam}_${subject}"} = $marksheet_data{$stud_adm};
									${$student_data{$stud_adm}}{"subject_count_${n_exam}"}++;
									${$student_data{$stud_adm}}{"total_${n_exam}"} += $marksheet_data{$stud_adm};	
									${$student_data{$stud_adm}}{"avg_${n_exam}"} = ${$student_data{$stud_adm}}{"total_${n_exam}"} / ${$student_data{$stud_adm}}{"subject_count_${n_exam}"};
								}
							}
						}
					}
						
					#rank students
					#simple strategy: do a sort, use a cntr to keep track of 
					#ranks. 1 cntr tracks the overall rank, (a hash of => others)
					#tracks the rank for each class
					#to deal with 

					my %means = ();

					my %class_rank_cntr = ();

					foreach (keys %stud_rolls) {
						my $class = ${$stud_rolls{$_}}{"class"};
						$class_rank_cntr{$class} = 0;
					}
					my $overall_cntr = 0;

					#determine overall rank
					#all this code can probably be replaced
					#with a  neat subroutine
					#TODO	
				
					for my $stud (sort {${$student_data{$b}}{"avg_$exam"} <=> ${$student_data{$a}}{"avg_$exam"} } keys %student_data) {
						${$student_data{$stud}}{"overall_rank"} = ++$overall_cntr;
						my $class = ${$student_data{$stud}}{"class"}; 
						${$student_data{$stud}}{"class_rank"} = ++$class_rank_cntr{$class};
					}
	
					my $prev_rank = -1;
					my $prev_avg = -1;
					#deal with ties in overall_rank
					for my $stud_2 (sort { ${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
						my $current_rank = ${$student_data{$stud_2}}{"overall_rank"};
						my $current_avg = ${$student_data{$stud_2}}{"avg_$exam"};

						#if ($prev_rank >= 0) {
							#tie
							if ($prev_avg == $current_avg) {
								${$student_data{$stud_2}}{"overall_rank"} = $prev_rank;	
							}
						#}
						$prev_rank = ${$student_data{$stud_2}}{"overall_rank"};
						$prev_avg  = $current_avg;
					}


					#handle ties in class_rank 
					my %class_rank_cursor = ();

					foreach (keys %stud_rolls) {
						my $class = ${$stud_rolls{$_}}{"class"};
						$class_rank_cursor{$class} = {"prev_rank" => -1, "prev_avg" => -1};
					}

					for my $stud_3 (sort {${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
						my $class = ${$student_data{$stud_3}}{"class"};
				
						my $current_rank = ${$student_data{$stud_3}}{"class_rank"};
						my $current_avg = ${$student_data{$stud_3}}{"avg_$exam"};
							
						#if (${$class_rank_cursor{$class}}{"prev_rank"} >= 0) {
							#tie
							if (${$class_rank_cursor{$class}}{"prev_avg"} == $current_avg) {
								${$student_data{$stud_3}}{"class_rank"} = ${$class_rank_cursor{$class}}{"prev_rank"};
							}
						#}
						${$class_rank_cursor{$class}}{"prev_rank"} = ${$student_data{$stud_3}}{"class_rank"};
						${$class_rank_cursor{$class}}{"prev_avg"}  = $current_avg;
					}

					#determine adm_ranks
					my $adm_rank = 0;

					for my $stud_4 (sort { ${$student_data{$b}}{"marks_at_adm"} <=> ${$student_data{$a}}{"marks_at_adm"} } keys %student_data) {
						#students with no 'marks at admission will have a rank of 'N/A'
						if (${$student_data{$stud_4}}{"marks_at_adm"} >= 0) {
							${$student_data{$stud_4}}{"admission_rank"} = ++$adm_rank;
						}
					}

					#deal with ties
					$prev_rank = -1;
					my $prev_marks_at_adm = -1;
						
					for my $stud_5 (sort { ${$student_data{$a}}{"admission_rank"} <=> ${$student_data{$b}}{"admission_rank"} } keys %student_data) {
						my $current_rank = ${$student_data{$stud_5}}{"admission_rank"};
						my $current_marks_at_adm = ${$student_data{$stud_5}}{"marks_at_adm"};

						#if ($prev_rank >= 0) {
							#tie
							if ($prev_marks_at_adm == $current_marks_at_adm) {
								${$student_data{$stud_5}}{"admission_rank"} = $prev_rank;	
							}
						#}
						$prev_rank = ${$student_data{$stud_5}}{"admission_rank"};
						$prev_marks_at_adm  = $current_marks_at_adm;
					}
	
					#to ensure students whose marks_at_adm,avg are not
					#set don't interfere with the ranking, their marks_at_adm,avg
					#is set to -1
					#now set this value to N/A

					for my $stud_7 (keys %student_data) {
						if (${$student_data{$stud_7}}{"marks_at_adm"} == -1) {
							${$student_data{$stud_7}}{"marks_at_adm"} = "N/A";
						}
						foreach ($exam, keys %included_exams) {
							if (${$student_data{$stud_7}}{"avg_$_"} == -1) {
								${$student_data{$stud_7}}{"avg_$_"} = "N/A";
							}
						}
					}

					my %images = ();
					opendir (my $dirh, "${doc_root}images/mugshots/");
					if ($dirh) {	
						my @image_list = readdir($dirh);
						for my $image (@image_list) {
							if ($image =~ /^(\d+)\./) {
								my $adm = $1;
								$images{$adm} = "/images/mugshots/$image";
							}
						}
					}
					else {
						print STDERR "Could not open 'mugshots' directory: $!\n";	
					}

					my $res = "";

					for my $stud_6 (sort { ${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
						
						next if (not exists $classes{lc(${$student_data{$stud_6}}{"class"})});
						#add new page to roll
						if ($pdf_mode) {
							$page = $pdf->page();
							#if ($page) {
								$page->mediabox("A4");
						#		($llx,$lly,$urx,$ury) = $page->get_mediabox();
							#}
						#	else {
						#		$pdf_mode = 0;
						#	}
						}

						#letterhead
						#----------
						#|********|
						#|        |
						#|        |
						#|	  |
						#|_ _ _ _ |
						#
						#** - Letterhead
						if ($pdf_mode) {
							my $image_obj = undef;
							my $image_n = "${doc_root}images/letterhead.png";

							if (-e $image_n) {
						
								$image_obj = $pdf->image_png($image_n); 

								my $graph_content = $page->gfx();
	
								my ($img_width, $img_height) = ($image_obj->width, $image_obj->height);

								#limit letterhead to x(47,547) and y(830,731);
								($llx, $urx, $lly, $ury) = (47, 547, 840, 740);

								my $scale = 1;

								#scale the image if it exceeds A4 
							
								if (($img_width + 6) > ($urx - $llx) or ($img_height + 6) > ($lly - $ury)) {
									my $width_scale = (($urx - $llx) - 6) / $img_width;
									my $height_scale = (($lly - $ury) - 6) / $img_height;
									#use the smaller of the 2
									$scale = $width_scale < $height_scale ? $width_scale : $height_scale; 
								}

								my $height_offset = int( ( ($lly - $ury) - ($img_height * $scale)) / 2 );
								my $width_offset  = int( ( ($urx - $llx) - ($img_width * $scale)) / 2 );

								$graph_content->image($image_obj, 47 + $width_offset, 740 + $height_offset, $scale);	
								my $x_pos = int ((500 - guess_width($exam, 13)) / 2);

								my $txt_content = $page->text();
								$txt_content->font($pdf->corefont("Times-Bold"), 13); 
								$txt_content->translate($x_pos, 725);
								$txt_content->text($exam);
							}
						}
						else {
							my $img_height = "100%";
							my $img_width = "100%";
	
							my $magick = Image::Magick->new;

							my ($width, $height, $size, $format) = $magick->Ping("${doc_root}images/letterhead.png");
							my $scale = 1;	
							if ($width > 150 or $height > 150) {
								my $width_scale = 150/$width;
								my $height_scale = 150/$height;

								$scale = $width_scale < $height_scale ? $width_scale : $height_scale;
								$img_height = $height * $scale;
								$img_width  = $width * $scale;
							}

							$res .=
qq{
<div style="width: 200mm; text-align: center; height: 280px; overflow: auto; border: none">
<img src="/images/letterhead.png" alt="" href="/images/letterhead.png" height="${img_height}px" width="${img_width}px">
<br>
<h3>$current_exam</h3>
</div>
<br>
}; 
						}
						#left align the image,
						#show data on its left
						my $pic = 0; 
						if ($show_pictures) {
							if ( exists $images{$stud_6} ) {
								$pic++;
							} 
						}
						if ($pic) {
							#organize with image
							if ($pdf_mode) {
								my $image_obj = undef;
								my $image_n = qq!/var/www/html$images{$stud_6}!;

								if (-e $image_n) {
									if ($image_n =~ /\.png$/i) {
										$image_obj = $pdf->image_png($image_n); 
									}

									elsif ($image_n =~ /\.jpe?g$/i) {
										$image_obj = $pdf->image_jpeg($image_n);
									}
	
									elsif ($image_n =~ /\.pnm$/i) {
										$image_obj = $pdf->image_pnm($image_n);
									}

									elsif ($image_n =~ /\.gif$/i) {
										$image_obj = $pdf->image_gif($image_n);
									}

									#assume bmp or look-alike 
									else {
										$image_obj = $pdf->image_gd(PDF::API2::Resource::XObject::Image->new($pdf, $image_n));
									}

									my $graph_content = $page->gfx();
	
									my ($img_width, $img_height) = ($image_obj->width, $image_obj->height);

									#limit passport to x(47,147) and y(721,601);
									#----------
									#|	  |
									#|***     |
									#|        |
									#|	  |
									#|_ _ _ _ |
									#
									#** - Passport
									($llx, $urx, $lly, $ury) = (47, 147, 721, 601);

									my $scale = 1;

									#scale the image if it exceeds  
							
									if (($img_width + 6) > ($urx - $llx) or ($img_height + 6) > ($lly - $ury)) {
										my $width_scale = (($urx - $llx) - 6) / $img_width;
										my $height_scale = (($lly - $ury) - 6) / $img_height;
										#use the smaller of the 2
										$scale = $width_scale < $height_scale ? $width_scale : $height_scale; 
									}

									my $height_offset = int( ( ($lly - $ury) - ($img_height * $scale)) / 2 );
									my $width_offset  = int( ( ($urx - $llx) - ($img_width * $scale)) / 2 );

									$graph_content->image($image_obj, 47 + $width_offset, 601 + $height_offset, $scale);	
									#----------
									#|	  |
									#|    ****|
									#|        |
									#|	  |
									#|_ _ _ _ |
									#
									#** - Profile
									my ($x_offset_1, $x_offset_2, $y_offset ) = (170, 218, 676);
									if ($show_admission_data) {
										$y_offset = 694;
										$x_offset_2 = 301;  
										if ($show_dorm) {
											$y_offset = 703;
											
										}									
									}
									#show_dorm with no show_admission_data
									elsif ($show_dorm) {
										$y_offset = 685;
										$x_offset_2 = 250;
									}
									my $txt_content = $page->text();

									my $bold = $pdf->corefont("Times-Roman");
									my $normal = $pdf->corefont("Times-Bold");
			
									#Adm No.: <adm_no>
									$txt_content->font($bold, 12);
									$txt_content->translate($x_offset_1, $y_offset);
									$txt_content->text("Adm No"); 

									$txt_content->font($normal, 12);
									$txt_content->translate($x_offset_2, $y_offset);
									$txt_content->text(qq!: $stud_6!);	
									$y_offset -= 18;

									#Name: <name>
									$txt_content->font($bold, 12);
									$txt_content->translate($x_offset_1, $y_offset);
									$txt_content->text("Name"); 

									$txt_content->font($normal, 12);
									$txt_content->translate($x_offset_2, $y_offset);
									$txt_content->text(qq!: ${$student_data{$stud_6}}{"name"}!);	
									$y_offset -= 18;

									#Class: <class>
									$txt_content->font($bold, 12);
									$txt_content->translate($x_offset_1, $y_offset);
									$txt_content->text("Class"); 

									$txt_content->font($normal, 12);
									$txt_content->translate($x_offset_2, $y_offset);
									$txt_content->text(qq!: ${$student_data{$stud_6}}{"class"}!);
	
									if ($show_admission_data) {
										$y_offset -= 18;

										#Marks at Admission: <marks_at_admission>
										$txt_content->font($bold, 12);
										$txt_content->translate($x_offset_1, $y_offset);
										$txt_content->text("Marks at Admission"); 

										$txt_content->font($normal, 12);
										$txt_content->translate($x_offset_2, $y_offset);
										$txt_content->text(qq!: ${$student_data{$stud_6}}{"marks_at_adm"}!);	
										$y_offset -= 18;

										#Rank at Admission: <rank_at_admission>
										$txt_content->font($bold, 12);
										$txt_content->translate($x_offset_1, $y_offset);
										$txt_content->text("Rank at Admission"); 

										$txt_content->font($normal, 12);
										$txt_content->translate($x_offset_2, $y_offset);
										$txt_content->text(qq!: ${$student_data{$stud_6}}{"admission_rank"}!);	
									}

									if ($show_dorm) {
										my $hse_dorm = ${$student_data{$stud_6}}{"house_dorm"};
										if (not defined $hse_dorm or $hse_dorm eq "") {
											$hse_dorm = "N/A";
										}
										
										$y_offset -= 18;								
										#House/Dorm: <house_dorm>
										$txt_content->font($bold, 12);
										$txt_content->translate($x_offset_1, $y_offset);
										$txt_content->text("House/Dorm"); 

										$txt_content->font($normal, 12);
										$txt_content->translate($x_offset_2, $y_offset);
										$txt_content->text(qq!: $hse_dorm!);	
									}
								}
							}
							else {
								my ($img_h,$img_w) = ("100%","100%");

								my $magick = Image::Magick->new;

								my ($width, $height, $size, $format) = $magick->Ping("${doc_root}$images{$stud_6}");	
								my $scale = 1;
								if ($width > 120 or $height > 150) {
									my $width_scale = 120/$width;
									my $height_scale = 150/$height;

									$scale = $width_scale < $height_scale ? $width_scale : $height_scale;
									$img_h = $height * $scale;
									$img_w = $width * $scale;
								}

								$res .=
qq!
<img src="$images{$stud_6}" height="$img_h" width="$img_w" style="float: left; margin: 4px">

<table style="padding-top: 3%">
<tr><td style="font-weight: bold">Adm No.:<td>$stud_6
<tr><td style="font-weight: bold">Name:<td>${$student_data{$stud_6}}{"name"}
<tr><td style="font-weight: bold">Class:<td>${$student_data{$stud_6}}{"class"}
!;
								if ($show_admission_data) {
									$res .=	
qq!
<tr><td style="font-weight: bold">Marks at Admission:<td>${$student_data{$stud_6}}{"marks_at_adm"}
<tr><td style="font-weight: bold">Rank at Admission:<td>${$student_data{$stud_6}}{"admission_rank"}
!;
								}
								if ($show_dorm) {
									my $hse_dorm = ${$student_data{$stud_6}}{"house_dorm"};
									if (not defined $hse_dorm or $hse_dorm eq "") {
										$hse_dorm = "N/A";
									}
									$res .=
qq!
<tr><td style="font-weight: bold">House/Dorm:<td>$hse_dorm
!;								}
								$res .=
qq!
</table>
<br><br>
!;
							}

						}
						else {
							#organize without image
							if ($pdf_mode) {
								#----------
								#|	  |
								#|********|
								#|        |
								#|	  |
								#|_ _ _ _ |
								#
								#** - Profile
								%data = ();
								#Adm No, Name, Class,( Marks at Admission, Rank at Admission, House/Dorm )? Headers
								$data{"1,1"} = {"data" => "Adm No.", "font-type" => "Times-Bold", "h-align" => "center"};
								$data{"1,2"} = {"data" => "Name", "font-type" => "Times-Bold", "h-align" => "center"};
								$data{"1,3"} = {"data" => "Class", "font-type" => "Times-Bold", "h-align" => "center"};
								if ($show_admission_data) {
									$data{"1,4"} = {"data" => "Marks at Admission", "font-type" => "Times-Bold", "h-align" => "center"};
									$data{"1,5"} = {"data" => "Rank at Admission", "font-type" => "Times-Bold", "h-align" => "center"};
								}

								if ($show_dorm) {
									$data{"1,6"} = {"data" => "House/Dorm", "font-type" => "Times-Bold", "h-align" => "center"};
								}

								$data{"2,1"} = {"data" => $stud_6, "h-align" => "center"};
								$data{"2,2"} = {"data" => ${$student_data{$stud_6}}{"name"}, "h-align" => "center"};
								$data{"2,3"} = {"data" => ${$student_data{$stud_6}}{"class"}, "h-align" => "center"};
								if ($show_admission_data) {
									$data{"2,4"} = {"data" => ${$student_data{$stud_6}}{"marks_at_adm"}, "h-align" => "center"};
									$data{"2,5"} = {"data" => ${$student_data{$stud_6}}{"admission_rank"}, "h-align" => "center"};
								}
								if ($show_dorm) {
									my $hse_dorm = ${$student_data{$stud_6}}{"house_dorm"};
									if (not defined $hse_dorm or $hse_dorm eq "") {
										$hse_dorm = "N/A";
									}
									$data{"2,6"} = {"data" => $hse_dorm, "h-align" => "center"};
								}

								($llx, $urx, $lly, $ury) = (47, 547,721,601);	
								draw_table(500, 100);
							}
							else {
								$res .=
qq!
<table style="text-align: justify; table-layout: fixed; width: 200mm; word-wrap: normal" border="1" cellspacing="5%" cellpadding="2%">
<thead>
<th>Adm No.
<th>Name
<th>Class
!;
								if ($show_admission_data) {
									$res .=
qq!
<th>Marks at Admission
<th>Rank at Admission
!;
								}
								if ($show_dorm) {
									$res .=
qq!
<th>House/Dorm
!;								}
								$res .=
qq!
</thead>
<tbody>
<tr>
<td>$stud_6
<td>${$student_data{$stud_6}}{"name"}
<td>${$student_data{$stud_6}}{"class"}
!;
								if ($show_admission_data) {
									$res .=
qq!
<td>${$student_data{$stud_6}}{"marks_at_adm"}
<td>${$student_data{$stud_6}}{"admission_rank"}
!;
								}
								if ($show_dorm) {
									my $hse_dorm = ${$student_data{$stud_6}}{"house_dorm"};
									if (not defined $hse_dorm or $hse_dorm eq "") {
										$hse_dorm = "N/A";
									}
									$res .=
qq!
<td>$hse_dorm
!;
								}
								$res .=
qq!
</tbody>
</table>
<br><br>
!;
							}
						}
						#results proper
						#----------
						#|	  |
						#|******* |
						#|******* |
						#|	  |
						#|_ _ _ _ |
						#
						#** - Results proper
						my $row = 1;
						%data = ();

						if ($pdf_mode) {

							#table headers: Subject, (Marks | exam_1..exam_n) (,Grade, Remarks)?
							$data{"1,1"} = {"data" => "Subject", "font-type" => "Times-Bold"};
							my $extra_cols = 0;
							#displaying more than 1 exam
							if (keys %included_exams) {
								$extra_cols = scalar(keys %included_exams);
								my $cnt = 2;
								foreach (sort { $included_exams_age{$a} <=>  $included_exams_age{$b} } keys %included_exams) {	
									$data{"1,$cnt"} = {"data" => $_};
									$cnt++;
								}
								$data{"1,$cnt"} = {"data" => $exam, "font-type" => "Times-Bold"};
							}
							else {
								$data{"1,2"} = {"data" => "Marks", "font-type" => "Times-Bold"};
							}
							
							if ($show_grade) {
								$data{"1," . (3 + $extra_cols)} = {"data" => "Grade", "font-type" => "Times-Bold"};
							}
							if ($show_remarks) {
								$data{"1," . (4 + $extra_cols)} = {"data" => "Remarks", "font-type" => "Times-Bold"};
							}
							if ($show_input_by) {
								$data{"1," . (5 + $extra_cols)} = {"data" => "Teacher", "font-type" => "Times-Bold"};
							}
						}
						else {
							$res .= 
qq!
<table border="1" style="text-align: center; width: 200mm;table-layout: fixed" cellspacing="5%" cellpadding="2%">
<thead>
<th>Subject
!;
							if ( keys %included_exams ) {
								foreach ( sort { $included_exams_age{$a} <=>  $included_exams_age{$b} } keys %included_exams) {
									$res .= "<th>$_";
								}
								$res .= "<th>$exam";
							}
							else {
								$res .= "<th>Marks";
							}

							if ($show_grade) {
								$res .= "<th>Grade";
							}
							if ($show_remarks) {
								$res .= "<th>Remarks";
							}
							if ($show_input_by) {
								$res .= "<th>Teacher";
							}
							$res .=
qq!
</thead>
<tbody>
!;
						}
					
						for (my $j = 0; $j < @valid_subjects; $j++) {
							if (exists ${$student_data{$stud_6}}{"subject_${exam}_$valid_subjects[$j]"}) {
								$row++;
								my $score = ${$student_data{$stud_6}}{"subject_${exam}_$valid_subjects[$j]"};
								my $grade = get_grade($score);
								my $remark = undef;
								
								if ($pdf_mode) {
									$data{"$row,1"} = {"data" => $valid_subjects[$j], "font-type" => "Times-Bold"};
									my $extra_cols = 0;
									#displaying more than 1 exam
									if (keys %included_exams) {
										$extra_cols = scalar(keys %included_exams);
										my $cnt = 2;
										foreach (keys %included_exams) {
											$data{"$row,$cnt"} = {"data" => ${$student_data{$stud_6}}{"subject_${_}_$valid_subjects[$j]"} };
											$cnt++;
										}
										$data{"$row,$cnt"} = {"data" => ${$student_data{$stud_6}}{"subject_${exam}_$valid_subjects[$j]"}, "font-type" => "Times-Bold"};
									}

									else {
										$data{"$row,2"} = {"data" => $score};
									}

									if ($show_grade) {
										$data{"$row," . (3 + $extra_cols)} = {"data" => $grade};
									}
									if ($show_remarks) {
										$remark = $remarks{$grade};
										$data{"$row," . (4 + $extra_cols)} = {"data" => $remark};
									}
									if ($show_input_by) {
										my $ta = "-";
										if (exists $teachers{"${exam}_$valid_subjects[$j]"}) {
											$ta = $teachers{"${exam}_$valid_subjects[$j]"};
										}
										$data{"$row," . (5 + $extra_cols)} = { "data" => $ta };
									} 
								}
								else {
									$res .= 
qq!
<tr>
<td style="font-weight: bold">$valid_subjects[$j]
!;
		
									#displaying more than 1 exam
									if (keys %included_exams) {			
										foreach (sort { $included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams) {
											$res .= qq!<td>${$student_data{$stud_6}}{"subject_${_}_$valid_subjects[$j]"}!;
										}
									}
									$res .= qq!<td style="font-weight: bold">${$student_data{$stud_6}}{"subject_${exam}_$valid_subjects[$j]"}!;	
								
								
									if ($show_grade) {
										$res .= "<td>$grade";
									}
									if ($show_remarks) {
										$remark = $remarks{$grade};
										$res .= "<td>$remark";
									}
									if ($show_input_by) {
										my $ta = "-";
										if (exists $teachers{"${exam}_$valid_subjects[$j]"}) {
											$ta = $teachers{"${exam}_$valid_subjects[$j]"};
										}
										$res .= "<td>$ta";
									}
								}
							}
						}	
	
						#results summary
						my $class_size = ${$stud_rolls{${$student_data{$stud_6}}{"roll"}}}{"size"};
						my $class_grad_year = ${$stud_rolls{${$student_data{$stud_6}}{"roll"}}}{"grad_year"};
						my $yr_size = 0;
					
						for my $roll (keys %stud_rolls) {
							next unless (${$stud_rolls{${$student_data{$stud_6}}{"roll"}}}{"grad_year"} eq $class_grad_year);
							$yr_size += ${$stud_rolls{$roll}}{"size"};
						}
	
						if ($pdf_mode) {
							#Mean Score
							my $extra_cols = scalar(keys %included_exams);
							$row++;
							$data{"$row,1"} = {"data" => "Mean Score", "font-type" => "Times-Bold"};
							
							if (keys %included_exams) {
								my $cnt = 2;
								foreach (sort {$included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams) {
									my $mean_score = ${$student_data{$stud_6}}{"avg_$_"};
									$mean_score = sprintf "%.4f", $mean_score;
									my $mean_grade = get_grade($mean_score);
									my $mean_remark = undef;
									$data{"$row,$cnt"} = {"data" => $mean_score};		
									$cnt++;
								}
							}

							my $mean_score = ${$student_data{$stud_6}}{"avg_$exam"};
							$mean_score = sprintf "%.4f", $mean_score;
							my $mean_grade = get_grade($mean_score);
							my $mean_remark = undef;

							$data{"$row," . (2 + $extra_cols)} = {"data" => $mean_score, "font-type" => "Times-Bold"};

							if ($show_grade) {
								$data{"$row," . (3 + $extra_cols)} = {"data" => $mean_grade, "font-type" => "Times-Bold"};
							}

							if ($show_remarks) {
								$mean_remark = $remarks{$mean_grade};
								$data{"$row," . (4 + $extra_cols)} = {"data" => $mean_remark, "font-type" => "Times-Bold"};
							}

							if ($show_input_by) {	
								$data{"$row," . (5 + $extra_cols)} = {"data" => "", "font-type" => "Times-Bold"};
							}

							#Rank in Class
							$row++;	
							$data{"$row,1"} = {"data" => "Rank in Class", "font-type" => "Times-Bold"};

							#use this to determine how to position
							#the rank in the borderless kludge
							my $num_of_cols = $extra_cols + 1;
							$num_of_cols++ if ($show_grade);
							$num_of_cols++ if ($show_remarks);
							$num_of_cols++ if ($show_input_by);
	
							#e.g. if I hav 5 cols(3 exams + show grade + show remarks)
							#preceding will be 2
							#following will be 2
							my $preceding = int($num_of_cols / 2);
							#remembered to leave 1 column for the data
							my $following = ($num_of_cols - $preceding) - 1;

							my $h_align = "center";
							if (($num_of_cols % 2) == 0 ) {
								$preceding--;
								$following++;
								$h_align = "right";
							}	
 
							#how to handle the closing of the right and left
							my ($left_border, $right_border) = ("0", "0");
							$left_border = "1" unless ($preceding);
							$right_border = "1" unless ($following);

							my $col_cnt = 2;	
							#prepend blank cells	
							for (my $i = 0; $i < $preceding; $i++) {
								my $border_left = "0";
								#ensure the 1st closes up the table
								if ($i == 0) {
									$border_left = "1";
								}
								$data{"$row,$col_cnt"} = {"data" => "", "border-right" => "0", "border-left" => $border_left};
								$col_cnt++;
							}

							$data{"$row,$col_cnt"} = {"data" => ${$student_data{$stud_6}}{"class_rank"} . " out of $class_size", "border-right" => $right_border, "border-left" => $left_border, "font-type" => "Times-Bold", "h-align" => $h_align};	
							$col_cnt++;

							#append blank data
							for (my $j = 0; $j < $following; $j++) {
								my $border_right = "0";
								#the last cell should close the table
								if ($j == $following-1) {
									$border_right = "1";	
								}
								$data{"$row,$col_cnt"} = {"data" => "", "border-right" => $border_right, "border-left" => "0"};
								$col_cnt++;
							}
							
							#Overall Rank
								
							$row++;
							
							$data{"$row,1"} = {"data" => "Overall Rank", "font-type" => "Times-Bold"};

							$col_cnt = 2;
						

							#prepend blank cells	
							for (my $i = 0; $i < $preceding; $i++) {
								my $border_left = "0";
								#ensure the 1st closes up the table
								if ($i == 0) {
									$border_left = "1";
								}
								$data{"$row,$col_cnt"} = {"data" => "", "border-right" => "0", "border-left" => $border_left};
								$col_cnt++;
							}

							$data{"$row,$col_cnt"} = {"data" => ${$student_data{$stud_6}}{"overall_rank"} . " out of $yr_size", "border-right" => $right_border, "border-left" => $left_border, "font-type" => "Times-Bold", "h-align" => $h_align};	
							$col_cnt++;

							#append blank data
							for (my $j = 0; $j < $following; $j++) {
								my $border_right = "0";
								#the last cell should close the table
								if ($j == $following-1) {
									$border_right = "1";	
								}
								$data{"$row,$col_cnt"} = {"data" => "", "border-right" => $border_right, "border-left" => "0"};
								$col_cnt++;
							}
						
							($llx, $urx, $lly, $ury) = (47, 547, 595,345);	
							draw_table(500,250); 
							my $all_cells = join(" | ", sort cell_ref_sort keys %data);
							
						}
						#amusing contrast between how much code it takes
						#to do this for a PDF(116 lines) and the HTML(37)
						else {
							$res .= 
qq!
<tr>
<td style="font-weight: bold">Mean Score
!;			
							if (keys %included_exams) {	
								foreach (sort {$included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams) {
									my $mean_score = ${$student_data{$stud_6}}{"avg_$_"};
									$mean_score = sprintf "%.4f", $mean_score;
									$res .= qq!<td>$mean_score!;	
								}
							}

							my $mean_score = ${$student_data{$stud_6}}{"avg_$exam"};
							$mean_score = sprintf "%.4f", $mean_score;
							my $mean_grade = get_grade($mean_score);
							my $mean_remark = undef;

							$res .= qq!<td style="font-weight: bold">$mean_score!;

							my $extra_cols = scalar(keys %included_exams);

							my $colspan = 1 + $extra_cols;
							if ($show_grade) {
								$res .= qq!<td style="font-weight: bold">$mean_grade!;
								$colspan++;
							}
							if ($show_remarks) {
								$mean_remark = $remarks{$mean_grade};
								$res .= qq!<td style="font-weight: bold">$mean_remark!;
								$colspan++;
							}

							if ($show_input_by) {
								$res .= "<td>&nbsp;";
								$colspan++;
							}
	
							$res .= 
qq!
<tr style="font-weight: bold"><td>Rank in Class<td colspan="$colspan">${$student_data{$stud_6}}{"class_rank"} out of $class_size
<tr style="font-weight: bold"><td>Overall Rank<td colspan="$colspan">${$student_data{$stud_6}}{"overall_rank"} out of $yr_size
</tbody>
</table>
<br>
!;
						}
						#extra-curriculae
						#----------
						#|	  |
						#|	  |
						#|.-.-.-.-|
						#|	  |
						#|_ _ _ _ |
						#
						#** - Results proper
						#extra-curriculars
						my ($respons,$gayms,$klubs) = ("-","-","-");

						if ($pdf_mode) {
							%data = ();
							#Responsibilities, Sports/Games, Clubs/Societies

							$data{"1,1"} = {"data" => "Responsibilities", "font-type" => "Times-Bold"};
							$data{"1,2"} = {"data" => "Games/Sports", "font-type" => "Times-Bold"};
							$data{"1,3"} = {"data" => "Clubs/Societies", "font-type" => "Times-Bold"};

							if (defined(${$student_data{$stud_6}}{"responsibilities"}) and ${$student_data{$stud_6}}{"responsibilities"} ne "") {
								$respons = join("\n", split/,/,${$student_data{$stud_6}}{"responsibilities"});
								
							}

							if (defined(${$student_data{$stud_6}}{"sports_games"}) and ${$student_data{$stud_6}}{"sports_games"} ne "") {
								$gayms = join("\n", split/,/,${$student_data{$stud_6}}{"sports_games"});
							}

							if (defined(${$student_data{$stud_6}}{"clubs_societies"}) and ${$student_data{$stud_6}}{"clubs_societies"} ne "") {
								$klubs = join("\n", split/,/,${$student_data{$stud_6}}{"clubs_societies"});
							}
						
							$data{"2,1"} = {"data" => $respons};
							$data{"2,2"} = {"data" => $gayms};
							$data{"2,3"} = {"data" => $klubs};

							($llx, $urx, $lly, $ury) = (47, 547,339,250);	
							draw_table(500,80);
						}
						else {
							$res .= 
qq!
<table border="1" style="table-layout: fixed; width: 200mm; text-align: center">
<thead>
<th>Responsibilities
<th>Games
<th>Clubs/Societies
</thead>
<tbody>
<tr>
!;
						
							if (defined(${$student_data{$stud_6}}{"responsibilities"}) and ${$student_data{$stud_6}}{"responsibilities"} ne "") {
								$respons = join("<BR>", split/,/,${$student_data{$stud_6}}{"responsibilities"});
								
							}

							if (defined(${$student_data{$stud_6}}{"sports_games"}) and ${$student_data{$stud_6}}{"sports_games"} ne "") {
								$gayms = join("<BR>", split/,/,${$student_data{$stud_6}}{"sports_games"});
							}

							if (defined(${$student_data{$stud_6}}{"clubs_societies"}) and ${$student_data{$stud_6}}{"clubs_societies"} ne "") {
								$klubs = join("<BR>", split/,/,${$student_data{$stud_6}}{"clubs_societies"});
							}
							$res .= "<td>$respons<td>$gayms<td>$klubs</tbody></table><br>";
						}

						#comments
						
						if ($pdf_mode) {
							my $txt_content = $page->text();
							my $graph_content = $page->gfx();

							my   $bold = $pdf->corefont("Times-Bold");	

							#Class Teacher's Comments
							$txt_content->font($bold, 14);
							$txt_content->translate(47, 231);
							$txt_content->text("Class Teacher's Comments");

							#Underline
							$graph_content->move(47, 229);
							$graph_content->line(212, 229);
							$graph_content->stroke();

							#spaces 
							my $y_offset = 204;
							my $height = 25;
							foreach (1..3) {
								$graph_content->move(47, $y_offset);
								for ( my $x = 47; $x < 372; $x += 9 ) {
									$graph_content->line($x + 6, $y_offset);
									$graph_content->move($x + 9, $y_offset);
								}
								$graph_content->stroke();
								$y_offset -= $height;
							}

							#Principal's Comments
							$txt_content->font($bold, 14);
							$txt_content->translate(47, 134);
							$txt_content->text("Principal's Comments");

							#Underline
							$graph_content->move(47, 132);
							$graph_content->line(187, 132);
							$graph_content->stroke();

							#Do not write below this line 
							$y_offset = 107;
							$height = 25;
							foreach (1..3) {
								$graph_content->move(47, $y_offset);
								for ( my $x = 47; $x < 372; $x += 9 ) {
									#Golden ratio(ish)-> 6:3
									$graph_content->line($x + 6, $y_offset);
									$graph_content->move($x + 9, $y_offset);
								}
								$graph_content->stroke();
								$y_offset -= $height;
							}

							#Guardian's Signature
							$txt_content->font($bold, 14);
							$txt_content->translate(47, 38);
							$txt_content->text("Parent/Guardian's Signature");

							#Underline
							$graph_content->move(47, 36);
							$graph_content->line(232, 36);
							$graph_content->stroke();

							$graph_content->move(47, 11);
							for ( my $x = 47; $x < 220; $x += 9 ) {
								#Golden ratio(ish)-> 6:3
								$graph_content->line($x + 6, 11);
								$graph_content->move($x + 9, 11);
							}
							$graph_content->stroke();

							#Date
							$txt_content->font($bold, 14);
							$txt_content->translate(238, 38);
							$txt_content->text("Date");

							#Underline
							$graph_content->move(238, 36);
							$graph_content->line(268, 36);
							$graph_content->stroke();

							$graph_content->move(238,11); 
							for ( my $x = 238; $x < 380; $x += 9 ) {
								#Golden ratio(ish)-> 6:3
								$graph_content->line($x + 6, 11);
								$graph_content->move($x + 9, 11);
							}
							$graph_content->stroke();
						}
						else {
							my $dots = "." x 500;
							$res .=
qq!
<table border="1" cellspacing="2%" style="width: 200mm; table-layout: fixed; word-wrap: break-word">
<tr>
<td colspan="2">
<span style="font-weight: bold; text-decoration: underline">Class Teacher's Comments</span><br>
<span style="line-height: 200%">$dots</span>
<tr>
<td colspan="2">
<span style="font-weight: bold; text-decoration: underline">Principal's Comments</span><br>
<span style="line-height: 200%">$dots</span>
<tr>
<td>
<span style="font-weight: bold; text-decoration: underline">Parent/Guardian's Signature</span><br>
<span style="line-height: 200%">....................................................</span>
<td>
<span style="font-weight: bold; text-decoration: underline">Date</span><br>
<span style="line-height: 200%">....................................................</span>
</table>
<br><br>
<hr>
!;
						}
					}

					#save pdf
					if ($pdf_mode) {
						$pdf->save();
					   	$content = 
qq{
<html>
<head>
<title>Spanj: Exam Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/reportcards/$filename.pdf">/reportcards/$filename.pdf</a>. If you were not, <a href="/reportcards/$filename.pdf">Click Here</a> 
</body>
</html>
};

						#log download report cards	
						my @today = localtime;
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

						open (my $log_f, ">>${log_d}user_actions-$day_month_yr.log");
       						if ($log_f) {
               						@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log download report cards for $id due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
							my $viewed_classes = join (',', keys %classes);
 
	 						print $log_f "$id DOWNLOAD REPORT CARDS ($viewed_classes) $time\n";
							flock ($log_f, LOCK_UN);
               						close $log_f;
       						}
						else {
							print STDERR "Could not log view report cards for $id: $!\n";
						}
						#exit 0;
					}
					else {
						$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
$res
<body>
</html>
};
						#log report card gen	
						my @today = localtime;
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

						open (my $log_f, ">>${log_d}user_actions-$day_month_yr.log");
       						if ($log_f) {
               						@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log view report cards for $id due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
							my $viewed_classes = join (',', keys %classes);
 
	 						print $log_f "$id VIEW REPORT CARDS ($viewed_classes) $time\n";
							flock ($log_f, LOCK_UN);
               						close $log_f;
       						}
						else {
							print STDERR "Could not log view report cards for $id: $!\n";
						}
					}
				}

				else {
					$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>None of the student rolls in the system match your selection.</em> Perhaps these rolls have not been created yet?
</body>
</html>
};

				}
			}
		}
		#confirm tokens issue
		else {
			$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>Invalid authorization tokens sent. Reload this page to continue.</em>
</body>
</html>
};
		}
	}

	else {
		if (@authd_classes) {
			my %grouped_classes = ();
			my %exams = ();
	
			#Group the classes by year
			for my $class (@authd_classes) {
				if ($class =~ /(\d+)/) {
					my $yr = $1;
					
					$grouped_classes{$yr} = [] unless (exists $grouped_classes{$yr});
					push @{$grouped_classes{$yr}}, $class;
				}
			}	
	 
			my $prep_stmt2 = $con->prepare("SELECT exam_name,max(time) FROM marksheets GROUP BY exam_name");
			if ($prep_stmt2) {
				my $rc = $prep_stmt2->execute();
				if ($rc) {
					while (my @rslts = $prep_stmt2->fetchrow_array()) {
						$exams{$rslts[0]} = $rslts[1];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM marksheets statement: $prep_stmt2->errstr$/";
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM marksheets statement: $prep_stmt2->errstr$/";
			}
	
			my $classes_select = '';
			my $exam_select = '';
	
			if (scalar(@authd_classes) > 1) {
				$classes_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL style="font-weight: bold">Class</LABEL>};

				foreach (sort keys %grouped_classes) {
					my @yr_classes = @{$grouped_classes{$_}};

					$classes_select .= "<TD>";
					for (my $i = 0; $i < scalar(@yr_classes); $i++) {
						$classes_select .= qq{<INPUT type="checkbox" name="class_$yr_classes[$i]" id="$yr_classes[$i]" value="$yr_classes[$i]"><LABEL for="class_$yr_classes[$i]" id="$yr_classes[$i]_label">$yr_classes[$i]</LABEL>};
						#do not append <BR> to the last class
						if ($i < $#yr_classes) {
							$classes_select .= "<BR>";
						}
					}
				}
				$classes_select .= "</table>"; 
			}
			else {
				my $class = $authd_classes[0];
				$classes_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL for="class_$class" style="font-weight: bold">Class</LABEL><TD><INPUT readonly type="text" name="class_$class" value="$class"></TABLE>};
			}
			$exam_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL style="font-weight: bold" for="exam">Exam</LABEL><TD><SELECT name="exam">};
			
			foreach ( sort { $exams{$a} <=> $exams{$b} } keys %exams) {	
				if ($_ eq $current_exam) {
					$exam_select .= qq{<OPTION selected value="$_">$_</OPTION>}; 
				}
				else {
					$exam_select .= qq{<OPTION value="$_">$_</OPTION>}; 
				}
			}
			$exam_select .= "</SELECT></TABLE>";
	
			my $included_exams = "";

			if (keys %exams > 1) {
				$included_exams .= qq{Also include the following exams in the report card:<BR><TABLE cellspacing="5%">};
				my $include_cntr = 0;

				foreach (sort { $exams{$a} <=> $exams{$b} } keys %exams) {
					$included_exams .= qq{<TR><TD><INPUT type="checkbox" name="include_$include_cntr" value="$_"><LABEL for="include_$include_cntr">$_</LABEL>};
					$include_cntr++;
				}
				$included_exams .= "</TABLE>";
			}

			my $conf_code = gen_token();
			$session{"confirm_code"} = $conf_code;
			$update_session++;	
			$content =
		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<FORM action="/cgi-bin/genreportcards.cgi" method="POST">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<p>$classes_select
<p>$exam_select
<p>$included_exams

<table>
<tr>
<td><INPUT type="submit" name="view" value="View Report Cards">
<td><INPUT type="submit" name="download" value="Download Report Cards">
</table>

</FORM>
</body>
</html>
};

		}
		else {

			my $err = "<em>Sorry you are not authorized to generate any report cards.</em> To continue, obtain an up to date token with the appropriate privileges from the administrator.";
			if ($full_user) {
				$err = "<em>The 'classes' system variable has not been properly configured.</em> To continue, change this system variable through the administrator panel.";
			}

			$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title> Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$err
</body>
</html>
};	
	
		}
	}
}

else { 
	$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title> Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>Sorry you are not authorized to generate any report cards.</em> To continue, obtain an up to date token with the appropriate privileges from the administrator.
</body>
</html>
};
}
if ($pdf_mode) {
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /reportcards/$filename.pdf\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
}
else {
	print "Status: 200 OK\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
}

my $len = length($content);
print "Content-Length: $len\r\n";

if ($update_session) { 
	my @new_sess_array = ();
	for my $sess_key (keys %session) {	
		push @new_sess_array, $sess_key."=".$session{$sess_key};        
	}
	my $new_sess = join ('&',@new_sess_array);
	print "X-Update-Session: $new_sess\r\n";
}

print "\r\n";
print $content;
$con->disconnect();

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub grade_sort {
	#idea is to try & give the student
	#the best grade their marks can
	#earn. Presumably, higher marks == better grade

		
	#both have a minimum
	#use the higher of the 2
	if (exists ${$grading{$a}}{"min"} and exists ${$grading{$b}}{"min"}) {
		return ${$grading{$b}}{"min"} <=> ${$grading{$a}}{"min"};
	}
	#both have a maximum
	#use the higher of the 2
	elsif (exists ${$grading{$a}}{"max"} and exists ${$grading{$b}}{"max"}) {
		return ${$grading{$b}}{"max"} <=> ${$grading{$a}}{"max"};
	}
	elsif (exists ${$grading{$a}}{"eq"} and exists ${$grading{$b}}{"eq"}) {
		return ${$grading{$b}}{"eq"} <=> ${$grading{$a}}{"eq"};
	}
	#$a has eq, $b doesn't 
	if (exists ${$grading{$a}}{"eq"}) {
		return 1;
	}
	#$b has eq, $a doesn't
	else {
		return -1;
	}  

	#$a has a min set, $b doesn't 
	if (exists ${$grading{$a}}{"min"}) {
		return 1;
	}
	#$b has a min set, $a doesn't
	else {
		return -1;
	}
}

sub get_grade {
	my $grade = "N/A";
	return "N/A" unless (@_);
	my $score = $_[0];

	GRADE: for my $tst_grade (sort grade_sort keys %grading) {
		my %tst_conds = %{$grading{$tst_grade}};
		#check equality
		if (exists $tst_conds{"eq"}) {
			if ($score == $tst_conds{"eq"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"min"}) {
			if ($score > $tst_conds{"min"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"max"}) {
			if ($score < $tst_conds{"max"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
	}
	return $grade;
}

#width,height,data
sub draw_table {
	return unless (scalar(@_) > 1);	
	my $width = shift;
	my $height = shift;	
	
	my ($display_width, $display_height) =  ($urx - $llx, $lly - $ury);
	
	my $x_offset = $llx + int ( ($display_width - $width ) / 2 );

	my $y_offset =  $lly - int ( ($display_height - $height ) / 2 );	

	my ($no_cols,$no_rows) = (0,0);	

	my %widths  = ();
	my %heights = ();
	my ($widths_total,$heights_total) = (0,0);
	my $overflows = 0;

	WRAP:
	{
		%widths  = ();
		%heights = ();
		($widths_total,$heights_total) = (0,0);	

		for my $cell (keys %data) {
			my $cell_dta = "undef";
			if (exists ${$data{$cell}}{"data"} and defined  ${$data{$cell}}{"data"}) {
				$cell_dta = ${$data{$cell}}{"data"};
			}	

			my $font_size = 12;	
			if ($cell =~ /^(\d+),(\d+)$/) {	
				my ($row,$col) = ($1,$2);
				my $cell_data = "";
				if (exists ${$data{$cell}}{"data"} and defined ${$data{$cell}}{"data"}) {
					$cell_data = ${$data{$cell}}{"data"};
				}

				my $cell_data_width = 0;	

				if ( exists ${$data{$cell}}{"font-size"} ) {
					my $possib_font_size = ${$data{$cell}}{"font-size"};
					if ($possib_font_size =~ /^\d+$/) {
						$font_size = $possib_font_size;
					}
				}
				if ( exists ${$data{$cell}}{"font-type"} ) {
					my $possib_font_name = ${$data{$cell}}{"font-type"};
					if ( exists $core_fonts{$possib_font_name} ) {
						my $font_name = $possib_font_name;
						if ($font_name =~ /Bold/) {	
							$font_size *= 1.2;
						}
					}
				}
			
				if ($auto_resize) {
					if ($cell_data =~ /\n/m) {	
						my @lines = split/\n/m,$cell_data;
						for my $line (@lines) {	
							my $width = guess_width($line, $font_size) + $font_size;
							if ($width > $cell_data_width) {	
								$cell_data_width = $width;
							}
						}
					}
					else {
						$cell_data_width = guess_width($cell_data, $font_size) + $font_size;
					}
 
					if (not exists $widths{$col}) {
						$widths{$col} = $cell_data_width;
						$widths_total += $cell_data_width;
					}
					else {
						if ($cell_data_width > $widths{$col}) {
							#replace existing widest both in %widths
							#and in widths_total 
							$widths_total -= $widths{$col};
							$widths{$col} = $cell_data_width;
							$widths_total += $cell_data_width;
						}
					}
				
					my $cell_data_height = $font_size * 2;
					if ($cell_data =~ /\n/m) {
						my @content_lines = split /\n/m, $cell_data;
						$cell_data_height = scalar(@content_lines) * $font_size;
						my $inter_line_spc = int ((scalar(@content_lines) - 1) * $font_size * 0.5);
						#my $inter_line_spc = (scalar(@content_lines) - 1) * $font_size * 0.5;
						$cell_data_height += $inter_line_spc + $font_size;
					}

					if (not exists $heights{$row}) {
						$heights{$row} = $cell_data_height;
						$heights_total += $cell_data_height;
					}
					else {
						if ($cell_data_height > $heights{$row}) {
							$heights_total -= $heights{$row};
							$heights{$row} = $cell_data_height;
							$heights_total += $cell_data_height;
						}
					}
				}
				if ($row > $no_rows) {
					$no_rows = $row;
				}
				if ($col > $no_cols) {
					$no_cols = $col;
				}
			}
		}	
	
		#try wrapping lines around spaces
		if ( $widths_total  > $width or $heights_total > $height ) {
			$overflows = 1;
	
			my $found_space = 0;
			J: for my $cell3 (sort { length( ${$data{$b}}{"data"} ) <=> length( ${$data{$a}}{"data"} ) }  keys %data) {
				
				my $cell3_data = ${$data{$cell3}}{"data"};	

				if ($cell3_data =~ /(\h+)/m) {
					$found_space++;
	
					my $new_line = "\n";
					$cell3_data =~ s/\h+/$new_line/m;

					#check possible exceed of table height
					#every split will add 1.5 font size to heights_total

					my $font_size = 12;
					
					if ( exists ${$data{$cell3}}{"font-size"} ) {
						my $possib_font_size = ${$data{$cell3}}{"font-size"};
						if ($possib_font_size =~ /^\d+$/) {
							$font_size = $possib_font_size;
						}
					}
					if ( exists ${$data{$cell3}}{"font-type"} ) {
						my $possib_font_name = ${$data{$cell3}}{"font-type"};
						if ( exists $core_fonts{$possib_font_name} ) {
							my $font_name = $possib_font_name;
							if ($font_name =~ /Bold/) {	
								$font_size *= 1.2;
							}
						}
					}

					#exceeded. break out in a sweat
					if ($heights_total + ($font_size * 1.5) > $height) {	
						$found_space = 0;
						last J; 
					}
					${$data{$cell3}}{"data"} = $cell3_data;
					last J;
				}
			}
	
			if ($found_space) {
				redo WRAP;
			}
			else {
				#reduce font sizes
				#up to 0pts---yeah, that's daft...
				my $new_font = 11;
				for my $cell4 (keys %data) {
					if (exists ${$data{$cell4}}{"font-size"} and ${$data{$cell4}}{"font-size"} =~ /^\d+$/) {
						$new_font = ${$data{$cell4}}{"font-size"} - 1;
					}
					if ($new_font < 0) {	
						last WRAP;
					}
					else {	
						${$data{$cell4}}{"font-size"} = $new_font;
					}
				}
				redo WRAP; 
			}
		}
		else {
			$overflows = 0;
			last WRAP;
		}
	}

	if ($auto_resize) {
		#resize each column
		#in ratio of their widest cells	

		foreach (keys %widths) {	
			$widths{$_} = int( ($widths{$_} / $widths_total) * $width);	
#			$widths{$_} = ($widths{$_} / $widths_total) * $width;
		}

		foreach (keys %heights) {	
			$heights{$_} = int( ($heights{$_} / $heights_total) * $height);	
#			$heights{$_} = ($heights{$_} / $heights_total) * $height;
		}
	}

	#default row,col sizes
	#assume uniform col,row spacing
	my ($row_height,$col_width) = (int($height / $no_rows), int($width / $no_cols));
#	my ($row_height,$col_width) = ($height / $no_rows, $width / $no_cols);
	my $text = $page->text(); 
	my $graph = $page->gfx();
	
	#draw enclosing box...
		
	$graph->move($x_offset, $y_offset);
	$graph->line($x_offset, $y_offset - ($row_height * $no_rows));
	#$graph->move($x_offset, $y_offset - $height);
	
	#$graph->line($x_offset + $width, $y_offset - $height);
	$graph->move($x_offset + $width, $y_offset - $height);

	#$graph->line($x_offset + $width, $y_offset);
	$graph->move($x_offset + sprintf("%.0f", $no_cols * $col_width), $y_offset);
	
	$graph->line($x_offset, $y_offset);
	$graph->stroke();

	#draw individual cells
#	$y_offset = $display_height - int ( ($display_height - $height ) / 2 );	
#	$y_offset = $display_height - ($display_height - $height ) / 2;
	
	my ($cell_x, $cell_y) = ($x_offset, $y_offset);	
	my ($row,$col) = (1,1);
			
	for my $cell2 (sort cell_ref_sort keys %data) {	
		if ($cell2 =~ /^(\d+),(\d+)$/) {
			($row,$col) = ($1,$2);
		}
		#set row,col sizes as appropriate
		#if auto_resize is on
		if ($auto_resize) {
			$row_height = $heights{$row};
			$col_width  = $widths{$col};	
		}
		
		#don't draw the line @ bottom
		#it has been sketched for thee
		#has double role- avoids the issue
		#created by the int() rounding of
		#row_height 
		#if ($row < $no_rows) {
			my $correction = 0;
			unless ( $width  / $no_cols % 10 == 0 ) {
				if ($col == $no_cols) {	
					#$correction = 1;
				}
			}
			#no bottom border
			#kludge for implementing rowspan
			unless (exists ${$data{$cell2}}{"border-bottom"} and ${$data{$cell2}}{"border-bottom"} eq "0") {
				$graph->move($cell_x, $cell_y - $row_height);	
				$graph->line($cell_x + $col_width + $correction, ($cell_y - $row_height));	
			}
		#}
		#do not draw the last line on right
		#if ($col < $no_cols) {
			my ($l_correction, $u_correction) = (0,0);
			#unless ($height / $no_rows) % 10 == 0) {
				if ( $row == $no_rows ) {
					unless ( $height / $no_rows  % 10 == 0 ) {
						#$l_correction = 3;
					}
				}
				if ($row == 1) {
					unless ( $height / $no_rows % 10 == 0 ) {
						#$u_correction = 3;
					}
				}
			#}
			unless (exists ${$data{$cell2}}{"border-right"} and ${$data{$cell2}}{"border-right"} eq "0") {
				$graph->move($cell_x + $col_width, $cell_y - $u_correction);
				$graph->line($cell_x + $col_width, ($cell_y - $row_height) - $l_correction);	
			}
		#}

		my $cell_content = ${$data{$cell2}}{"data"};	
	
		my $font_size = 12;
		my $font_name = "Times-Roman";
		my $bold = 0;
		my $font_size_scale = 1;

		if (exists ${$data{$cell2}}{"font-size"}) {
			my $possib_font_size = ${$data{$cell2}}{"font-size"};
			if ($possib_font_size =~ /^\d+$/) {		
				$font_size = $possib_font_size;
			}
		}

		if (exists ${$data{$cell2}}{"font-type"}) {
			my $possib_font_name = ${$data{$cell2}}{"font-type"};
			if (exists $core_fonts{$possib_font_name}) {
				$font_name = $possib_font_name;
				if ($font_name =~ /Bold/) {
					$bold = 1;
					$font_size_scale = 1.2;
				}
			}
		}
		my $font = $pdf->corefont($font_name);
		my $v_align = "middle";
		my $h_align = "left";
		
		if ($cell_content =~ /^\d+(\.\d+)?$/) {
			$h_align = "right";	
		}

		#valid v-aligns: top, bottom, middle
		if (exists ${$data{$cell2}}{"v-align"}) {
			my $possib_v_align = ${$data{$cell2}}{"v-align"};
			if ($possib_v_align =~ /^(?:top)|(?:bottom)|(?:middle)$/i) {
				$v_align = lc($possib_v_align);
			}
		}

		#valid h-align: left, right, center, justify
		if (exists ${$data{$cell2}}{"h-align"}) {
			my $possib_h_align = ${$data{$cell2}}{"h-align"};
			if ($possib_h_align =~ /^(?:left)|(?:right)|(?:center)|(?:justify)$/i) {
				$h_align = lc($possib_h_align);
			}
		}

		
	
		my ($content_width, $content_height) = (guess_width($cell_content, $font_size * $font_size_scale), $font_size * $font_size_scale);	
	
		#detect & fix overflows (by wrapping/reducing font size/resizing rows,cols);
	
		my $multi_line = 0;
		my @lines = ();
		if ($cell_content =~ /\n/m) {
			$multi_line++;
			@lines = split/\n/m,$cell_content;
			my ($width, $height) = (-1,-1);	
			foreach (@lines) {
				my $possib_width = guess_width($_,$font_size * $font_size_scale);
				if ($possib_width > $width) {
					$width = $possib_width;
				}
			}
			$content_width = $width;
			$content_height = scalar(@lines) * $font_size * $font_size_scale;
		}
	
		my ($content_offset_x, $content_offset_y) = (-1, -1);

		my (%center_x_offsets, %right_x_offsets);

		my $half_em = int($font_size * $font_size_scale * 0.5);
#		my $half_em = $font_size * $font_size_scale * 0.5;

		#allow half an em above
		if ($v_align eq "top") {
			$content_offset_y = $cell_y - ($half_em + ($font_size * $font_size_scale));
		}

		#allow half an em below
		elsif ($v_align eq "bottom") {
			if ($multi_line) {
				my $inter_line_spc = (scalar(@lines) - 1) * $font_size * $font_size_scale * 0.5;
				my $content_below_line = (scalar(@lines) - 1) * $font_size * $font_size_scale;
				$content_offset_y = ($cell_y - $row_height) + ($content_below_line + $inter_line_spc);
			}
			else {
				$content_offset_y = ($cell_y - $row_height) + $half_em;	
			}
		}

		elsif ($v_align eq "middle") {
			if ($multi_line) {
				my $inter_line_spc = scalar(@lines) * $font_size * $font_size_scale * 0.5;
				my $pre_spc = ($row_height - ($content_height + $inter_line_spc)) / 2;
				$content_offset_y = $cell_y - ($pre_spc + ($font_size * $font_size_scale * 1.5)); 	
			}
			else {
				$content_offset_y = $cell_y - (int(($row_height - $content_height) / 2) + $content_height);
#				$content_offset_y = $cell_y - (($row_height - $content_height) / 2) + $content_height;
			}
		}

		if ($h_align eq "left") {
			$content_offset_x = $cell_x + $half_em;
		}

		elsif ($h_align eq "right") {
			if ($multi_line) {	
				foreach (@lines) {
					my $content_width = guess_width($_);
					$right_x_offsets{$_} =  ($cell_x + $col_width) - ($content_width + $half_em) ;
				}
			}
			else {
				$content_offset_x = ($cell_x + $col_width) - ($content_width + $half_em);
			}
		}

		elsif ($h_align eq "center") {
			if ($multi_line) {	
				foreach (@lines) {
					my $content_width = guess_width($_, $font_size);
					$center_x_offsets{$_} =  $cell_x + int(($col_width - $content_width) / 2);
#					$center_x_offsets{$_} =  $cell_x + (($col_width - $content_width) / 2);
				}
			}
			else {
				$content_offset_x = $cell_x + int (($col_width - $content_width) / 2);
#				$content_offset_x = $cell_x + (($col_width - $content_width) / 2);
			}
		}
		elsif ($h_align eq "justify") {

			unless ($multi_line) {
				push @lines, $cell_content;
			}

			for (my $h = 0; $h < @lines; $h++) {
				my $content_width = guess_width($lines[$h],$font_size);
			
				my $surplus_px = ($col_width - ($font_size * $font_size_scale)) - $content_width;
				my $spaces = int(($surplus_px / ($font_size * $font_size_scale)) * 3.7);
		
				my $content_len = length($lines[$h]);
				my $spaces_per_char = 1;
				my $heisenberg = 1;
				my $surplus = 0;

				if ($spaces > $content_len) {
					$spaces_per_char = int($spaces / $content_len );
					#the spaces will fit precisely into the content
					#unlikely...
					if (($spaces_per_char * $content_len) == $spaces) {
						$heisenberg = 0;
					}
					else {
						$surplus = $spaces - ($spaces_per_char * $content_len);	
					}
				}
	
				my $new_content = "";
				my $brk_pnt = $content_len - 1;
	

				for (my $i = 0; $i < $content_len - 1; $i++) {
					my $char = substr($lines[$h], $i, 1);	
					my $num_spaces = $spaces_per_char;
				
					if ($heisenberg) {
						if ($surplus-- > 0) {
							$num_spaces++;
						}
					}
					#Due to the uncertainty introduced above,
					#ensure you do not overpad
					if (($spaces - $num_spaces) >= 0) {
						my $pre_pend = int ($num_spaces / 2);
						my $a_pend = ($pre_pend * 2) == $num_spaces ? $pre_pend : $pre_pend + 1;
	
						$new_content .= " " x $pre_pend;
						$new_content .= $char;
						$new_content .= " " x $a_pend;
						$spaces -= $num_spaces;
					}
					else {
						$new_content .= $char;
						$brk_pnt = $i + 1;
					}
				}
				#append all remaining spaces
				$new_content .= " " x $spaces;
	
				for (my $j = $brk_pnt; $j < $content_len; $j++) {
					my $char = substr($lines[$h], $j, 1);
					$new_content .= $char;	
				}
				if ($multi_line) {	
					$lines[$h] = $new_content;
				}
				else {
					$cell_content = $new_content;
				}
				$content_offset_x = $cell_x + int(($font_size * $font_size_scale) / 2);
#				$content_offset_x = $cell_x + (($font_size * $font_size_scale) / 2);
			}
		}
		unless ($multi_line) { 	
			$text->translate($content_offset_x, $content_offset_y);
		}
		$text->font($font, $font_size);

		if ($multi_line) {	
			for my $line (@lines) {
				if (keys %center_x_offsets) {
					if (exists $center_x_offsets{$line}) {
						$content_offset_x = $center_x_offsets{$line};
					}
				}
				elsif (keys %right_x_offsets) {
					if (exists $right_x_offsets{$line}) {
						$content_offset_x = $right_x_offsets{$line};
					}
				}
				
				$text->translate($content_offset_x, $content_offset_y);	
				$text->text($line);
				$content_offset_y -= ($font_size * $font_size_scale * 1.5);	
			}
		}
		else {
			$text->text($cell_content);
		}	
		#update co-ord system 
		$cell_x += $col_width;
		
		#reset cell_x to 0
		if ($col >= $no_cols) {	
			$cell_x = $x_offset;
			$cell_y -= $row_height;		
		}
	}
	$graph->stroke();

}

sub cell_ref_sort {
	if ($a =~ /^(\d+),(\d+)$/) {
		my ($a_row,$a_col) =($1,$2);
		if ($b =~ /^(\d+),(\d+)$/) {
			my ($b_row,$b_col) =($1,$2);
			my $row_cmp = $a_row <=> $b_row;
			#when matching within row... 
			if ($row_cmp == 0) {
				return $a_col <=> $b_col;
			}
			else {
				return $row_cmp;
			}
		}
	}
	return 0;	
}

#guess_width(str, font_size)
sub guess_width {
	my $str = shift @_;
	my $font_size = shift @_;
	my $width = 0;	
	for (my $i = 0; $i < length($str); $i++) {
		my $char = substr($str,$i,1);	
		#UC: 0.75	
		if ($char =~ /[A-Z]/) {
			$width += 0.78;	
		}
		#lc: 0.46
		elsif ($char =~ /[a-z]/) {
			$width += 0.50;	
		}
		#numerals: 0.5
		elsif ($char =~ /[0-9]/) {
			$width += 0.54;	
		}
		#punctuation mark?: 0.42
		else {
			$width += 0.46;	
		}
	}
	return int($width * $font_size);
}
