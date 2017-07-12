#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;
use Spreadsheet::WriteExcel;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root);
my $logd_in = 0;
my $id;
my $full_user = 0;

my %session;
my $update_session = 0;

my @vm_classes = ();

my $spreadsheet_mode = 0;


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
							if ($_ =~ m!^VM\(([^\)]+)\)$!) {	
								push @vm_classes, $1;
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
	print "Location: /login.html?cont=/cgi-bin/viewmarksheet.cgi\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
   	my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/cgi-bin/viewmarksheet.cgi\">/login.html?cont=/cgi-bin/viewmarksheet.cgi</a>. If you were not, <a href=\"/cgi-bin/viewmarksheet.cgi\">Click Here</a> 
		</body>
                </html>";

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

my $content = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/viewmarksheet.cgi">View Marksheet</a>
	<hr> 
};

my $con;
my %grading;
my %points;

if (@vm_classes or $full_user) {
	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
	#discover the 'exam'
	#and 'classes' variables 

	my $current_exam = "";
	my @valid_classes = ();
	my %grouped_classes;
	my @valid_subjects = ();
	
	my %exams;
	
	my $show_adm_data = 0;
	my $show_grade = 0;
	my $show_point_average = 0;
	
	my $prep_stmt = $con->prepare("SELECT id,value FROM vars WHERE id='1-exam' OR id='1-classes' OR id='1-subjects' OR id='1-show admission data' OR id='1-grading' OR id='1-show grade in marksheet' OR id='1-show point average' OR id='1-points' LIMIT 8");
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

				elsif ($rslts[0] eq "1-show admission data") {
					if (defined($rslts[1]) and $rslts[1] eq "yes") {
						$show_adm_data++;
					}
				}
				elsif ($rslts[0] eq "1-show grade in marksheet") {
					if (defined($rslts[1]) and $rslts[1] eq "yes") {
						$show_grade++;
					}
				}

				elsif ($rslts[0] eq "1-show point average") {
					if (defined($rslts[1]) and $rslts[1] eq "yes") {
						$show_point_average++;
					}	
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

				elsif ($rslts[0] eq "1-points") {
					my $points_str = $rslts[1];
					my @points_bts = split/,/,$points_str;
					foreach (@points_bts) {
						if ($_ =~ /^([^:]+):\s*(.+)/) {
							my ($grade,$points) = ($1,$2);
							$points{$grade} = $points;	
						}
					}
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: ", $prep_stmt->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt->errstr, $/;
	}
		
	my @classes = ();
	if ($full_user) {
		@classes = @valid_classes;

	}

	else {
		#why did I not just @classes = @vm_classes?
		#well, I'm paranoid: I don't trust @vm_classes

		 for my $valid_class (@valid_classes) {
			A: for my $vm_class (@vm_classes) {
				if (lc($valid_class) eq lc($vm_class)) {
					push @classes, $valid_class;
					last A;
				}
			}
		}
	}

	#user has been presented with options
	#and they have made their choice
	if ($post_mode) {
		#check confirm code
		if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"}) {
			
			#verify authority to edit this class
			my $fail = 0;
			my $err_str = "";

			if (exists $auth_params{"download"}) {
				$spreadsheet_mode = 1;
			}
			my $exam = undef; 
			if (exists $auth_params{"exam"}) { 
				$exam = $auth_params{"exam"};
			}
			else {
				$fail = 1;
				$err_str = "Sorry you did not select any exam.";
			}
			my %classes;
	
			my $cntr = 0;
			
			B: foreach (keys %auth_params) {
				if ($_ =~ /^class_/) {
					my $class = $auth_params{$_};
					my $match = 0;
					C: foreach (@classes) {
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
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
</head>
<body>
$header
<em>$err_str</em>
</body>
</html>
};
			}
			else {
				#verify gen'ng marksheet for yearmates
				$fail = 0;	
				if (keys %classes > 1) {
					my $yr = undef;	
					D: foreach (keys %classes) {
						my $current_yr = "";
						if ($_ =~ /(\d+)/) {
							$current_yr = $1;
						}
						if (defined $yr) {
							unless ($current_yr eq $yr) {
								$fail++;
								last D;
							}
						}
						else {
							$yr = $current_yr;
						}
					}
				}

				if ($fail) {
					$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
</head>
<body>
$header
<em>Invalid class selection.</em> When selecting multiple classes, you can only select different streams of the same class.
</body>
</html>
};
				}
				else {
					#valid request- OK confirmation code, authorized class
					#and yearmates
					my $class_name = (keys %classes)[0];	
					my ($class_year,$start_year) = (-1,-1);
					if ($class_name =~ /(\d+)/) {
						$class_year = $1;
						my $current_year = (localtime)[5] + 1900;
						if ($exam =~ /\D*(\d{4,})\D*/) {
							$current_year = $1;
						}
						$start_year = 1 + ($current_year - $class_year);
					}	
					my %stud_rolls;
					my $matched_rolls = 0;

					my $prep_stmt3 = $con->prepare("SELECT table_name,class,grad_year FROM student_rolls WHERE start_year=?");
					if ($prep_stmt3) {
						my $rc = $prep_stmt3->execute($start_year);
						if ($rc) {
							while (my @rslts = $prep_stmt3->fetchrow_array()) {
								$rslts[1] =~ s/\d+/$class_year/;
								$stud_rolls{$rslts[0]} = {"class" => $rslts[1], "grad_year" => $rslts[2]};
								$matched_rolls++;
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt3->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt3->errstr, $/;
					}
					if ($matched_rolls) {
						my @where_clause_bts = ();
						foreach (keys %stud_rolls) {
							push @where_clause_bts, "roll=?";
						}
						my $where_clause = join(' OR ', @where_clause_bts);

				      		my $prep_stmt4 = $con->prepare("SELECT table_name,roll,subject FROM marksheets WHERE exam_name=? AND ($where_clause)");
						if ($prep_stmt4) {

							my @exec_params = keys %stud_rolls;
							unshift @exec_params,$exam;

							my $rc = $prep_stmt4->execute(@exec_params);
							if ($rc) {
								while (my @rslts = $prep_stmt4->fetchrow_array()) {
									${$stud_rolls{$rslts[1]}}{"marksheet_" . $rslts[2]} = $rslts[0];	
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
						}

							$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
</head>
<body>
$header
};

						#read student rolls
						#save adm,marks at admission & subjects
						my %student_data;

						for my $roll (keys %stud_rolls) {
							my $class = ${$stud_rolls{$roll}}{"class"};

							my $prep_stmt5 = $con->prepare("SELECT adm,s_name,o_names,marks_at_adm,subjects FROM `$roll`");
							if ($prep_stmt5) {

								my $rc = $prep_stmt5->execute();
								if ($rc) {
									while (my @rslts = $prep_stmt5->fetchrow_array()) {
										my ($adm,$s_name,$o_names,$marks_at_adm,$subjects) = @rslts;
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
										"mean_grade" => "-",
										"point_total" => 0,
										"point_average" => 0,
										"admission_rank" => "N/A",
										"class_rank" => 1,
										"overall_rank" => 1,
										"class" => $class
										};
										#preset the values of subjects to N/A
										my @subjects_list = split/,/, $subjects;
										foreach (@subjects_list) {	
											${$student_data{$adm}}{"subject_$_"} = "N/A";
											${$student_data{$adm}}{"grade_subject_$_"} = "-";	
										}
									}
								}
								else {
									print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
							}
						}
						
						#read the marksheets in DB:-
						#for each marksheet, update student_data	
						#in the switch from F2-F3 the student's
						#'subjects' records are changed
						#RULE: assume subjects can be removed but not
						#added. Therefore, any missing records in the 
						#{"subjects"} field are N/A
						#any additional values however, are allowed
						
						for my $stud_roll (keys %stud_rolls) {
							my %recs = %{$stud_rolls{$stud_roll}};		
							for my $rec_key (keys %recs) {
								my $prep_stmt5;
								if ($rec_key =~ /^marksheet_(.+)$/) {
									my $subject = $1;
									my $marksheet = $recs{$rec_key};
									
									$prep_stmt5 = $con->prepare("SELECT adm,marks FROM `$marksheet`");
									my %marksheet_data = ();
									if ($prep_stmt5) {
									
										my $rc = $prep_stmt5->execute();
										if ($rc) {
											while (my @rslts = $prep_stmt5->fetchrow_array()) {
												next unless (defined $rslts[0] and defined $rslts[1]);
												$marksheet_data{$rslts[0]} = $rslts[1];
											}
										}
										else {
											print STDERR "Could not execute SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
										}
									}
									else {
										print STDERR "Could not prepare SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
									}
									for my $stud_adm (keys %marksheet_data) {
										
 										${$student_data{$stud_adm}}{"subject_$subject"} = $marksheet_data{$stud_adm};
										my $grade = get_grade($marksheet_data{$stud_adm});

										if ($show_grade) {	
											${$student_data{$stud_adm}}{"grade_subject_$subject"} = $grade;
										}
									
										${$student_data{$stud_adm}}{"subject_count"}++;

										if ($show_point_average) {
											${$student_data{$stud_adm}}{"point_total"} += $points{$grade};
											${$student_data{$stud_adm}}{"point_average"} = ${$student_data{$stud_adm}}{"point_total"} / ${$student_data{$stud_adm}}{"subject_count"};
										}

										${$student_data{$stud_adm}}{"total"} += $marksheet_data{$stud_adm};	
										${$student_data{$stud_adm}}{"avg"} = ${$student_data{$stud_adm}}{"total"} / ${$student_data{$stud_adm}}{"subject_count"};
										if ($show_grade) {
											${$student_data{$stud_adm}}{"mean_grade"} = get_grade(${$student_data{$stud_adm}}{"avg"});
										}
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

						for my $stud (sort {${$student_data{$b}}{"avg"} <=> ${$student_data{$a}}{"avg"} } keys %student_data) {
							${$student_data{$stud}}{"overall_rank"} = ++$overall_cntr;
							my $class = ${$student_data{$stud}}{"class"};	
							${$student_data{$stud}}{"class_rank"} = ++$class_rank_cntr{$class};

							for my $stud_rec (keys %{$student_data{$stud}}) {
								if ($stud_rec =~ /^subject_(.+)$/) {
									my $subject = $1;
									my $score = ${$student_data{$stud}}{$stud_rec};	
									if ($score =~ /^\d+$/) {	
										${$means{$class}}{"total_" . $subject} += $score;
										${$means{$class}}{"count_" . $subject}++;
										${$means{$class}}{"avg_" . $subject} = ${$means{$class}}{"total_" . $subject} / ${$means{$class}}{"count_" . $subject};
										${$means{$class}}{"grade_" . $subject} = get_grade(${$means{$class}}{"avg_" . $subject});
									}
								}
								if ($stud_rec =~ /^avg$/) {	
									my $avg = ${$student_data{$stud}}{"avg"};
									if ($avg >= 0) {
										${$means{$class}}{"total_avg"} += $avg;
										${$means{$class}}{"count_avg"}++;
										${$means{$class}}{"avg"} = ${$means{$class}}{"total_avg"} / ${$means{$class}}{"count_avg"};
										${$means{$class}}{"mean_grade"} = get_grade(${$means{$class}}{"avg"});
									}
								}
								if ($show_point_average) {
									if ($stud_rec =~ /^point_average$/) {
										${$means{$class}}{"total_point_avg"} += ${$student_data{$stud}}{"point_average"};
										${$means{$class}}{"count_point_avg"}++;
										${$means{$class}}{"point_avg"} = ${$means{$class}}{"total_point_avg"} / ${$means{$class}}{"count_point_avg"};
									}
								}
							}
						}
	
						my $prev_rank = -1;
						my $prev_avg = -1;
						#deal with ties within class
						for my $stud_2 (sort { ${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
							my $current_rank = ${$student_data{$stud_2}}{"overall_rank"};
							my $current_avg = ${$student_data{$stud_2}}{"avg"};

							#if ($prev_rank >= 0) {
								#tie
								if ($prev_avg == $current_avg) {
									${$student_data{$stud_2}}{"overall_rank"} = $prev_rank;	
								}
							#}
							$prev_rank = ${$student_data{$stud_2}}{"overall_rank"};
							$prev_avg  = $current_avg;
						}

						my %class_rank_cursor = ();

						foreach (keys %stud_rolls) {
							my $class = ${$stud_rolls{$_}}{"class"};
							$class_rank_cursor{$class} = {"prev_rank" => -1, "prev_avg" => -1};
						}

						for my $stud_3 (sort {${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
							my $class = ${$student_data{$stud_3}}{"class"};
				
							my $current_rank = ${$student_data{$stud_3}}{"class_rank"};
							my $current_avg = ${$student_data{$stud_3}}{"avg"};
							
							#if (${$class_rank_cursor{$class}}{"prev_rank"} >= 0) {
								#tie
								if (${$class_rank_cursor{$class}}{"prev_avg"} == $current_avg) {
									${$student_data{$stud_3}}{"class_rank"} = ${$class_rank_cursor{$class}}{"prev_rank"};
								}
							#}
							${$class_rank_cursor{$class}}{"prev_rank"} = ${$student_data{$stud_3}}{"class_rank"};
							${$class_rank_cursor{$class}}{"prev_avg"}  = $current_avg;
						}

						if ($show_adm_data) {
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
						}
						my $header = "";
						my $single_class = 0;
						#where from the $roll?
						my $only_class = (keys %classes)[0];	
						my $first_stud_roll = "";

						J: for my $tst_roll (keys %stud_rolls) {
							if ( lc(${$stud_rolls{$tst_roll}}{"class"}) eq lc($only_class) ) {
								$first_stud_roll = $tst_roll;
								last J;
							}
						}

						#in spreadsheet mode
						#set up workbook, worksheets & bold format
						my ($workbook,$worksheet,$bold,$default_props,$spreadsheet_name, $row,$col) = (undef,undef,undef,undef,0,0);
						my $res = '';			
						if ($spreadsheet_mode) {

							$spreadsheet_name = join("_", keys %classes) . $exam . ".xls";
							$spreadsheet_name =~ s/\s/_/g; 

							$workbook = Spreadsheet::WriteExcel->new("${doc_root}/marksheets/$spreadsheet_name");
							if (defined $workbook) {

								$bold = $workbook->add_format( ("bold" => 1) );
								$default_props = $workbook->add_format( () );
								my $class_list = join(", ", keys %classes);
								$workbook->set_properties( ("title" => "Exam: $exam; Class/es: $class_list", "comments" => "lecxEetirW::teehsdaerpS htiw detaerC; User: $id") );
								$worksheet = $workbook->add_worksheet();
								$worksheet->set_landscape();
								$worksheet->hide_gridlines(0);
							}
							else {
								print STDERR "Could not create workbook: $!$/";
								$spreadsheet_mode = 0;
							}
						}
						#Dealing with just 1 class: display class & year
						if (scalar (keys %classes) == 1) {
							$single_class++;
							if ($spreadsheet_mode) {
								$worksheet->fit_to_pages(1,1);
								my %merge_props = ("valign" => "vcenter", "align" => "center", "bold" => 1, "size" => 14);
								my $merge_format = $workbook->add_format(%merge_props);
	
								$worksheet->merge_range($row, 0, $row, 20, qq!$only_class (Graduating Class of ${$stud_rolls{$first_stud_roll}}{"grad_year"}) - $exam!,$merge_format);
								$row++;
							}
							else {
								$header = qq!<h3>$only_class (Graduating Class of ${$stud_rolls{$first_stud_roll}}{"grad_year"}) - $exam</h3>!;
							}
						}

						#Multiple classes, display just the year
						else {
							if ($spreadsheet_mode) {
								my %merge_props = ("valign" => "vcenter", "align" => "center", "bold" => 1, "size" => 14);
								my $merge_format = $workbook->add_format(%merge_props);
	
								$worksheet->merge_range($row, 0, $row, 20, qq!Graduating Class of ${$stud_rolls{$first_stud_roll}}{"grad_year"} - $exam!, $merge_format);
								$row++;
							}
							else {
								$header = qq!<h3>Graduating Class of ${$stud_rolls{$first_stud_roll}}{"grad_year"} - $exam</h3>!;
							}
						}

						#counter Adm Name Class
						if ($spreadsheet_mode) {
							$worksheet->write_blank ($row, 0, $bold);
							$worksheet->write_string($row, 1, "Adm", $bold);
							$worksheet->write_string($row, 2, "Name", $bold);
							$worksheet->write_string($row, 3, "Class", $bold);
							$col = 4;
						}
						else { 
							$res = 
qq{
$header
<TABLE border="1" cellspacing="5%">
<THEAD>
<TH></TH><TH>Adm<TH>Name<TH>Class
};
						}
						for (my $i = 0; $i < @valid_subjects; $i++) {
							#append subjects headers
							if ($spreadsheet_mode) {
								$worksheet->write_string($row, $col, $valid_subjects[$i], $bold);
								$col++;
							}
							else {
								$res .= qq{<TH>$valid_subjects[$i]};
							}
						}

						#Mean Score | Point Average? | Rank At adm? | Class Rank | Overall Rank
						if ($spreadsheet_mode) {
							$worksheet->write_string($row, $col, "Mean Score", $bold);	
							if ($show_point_average) {	
								$worksheet->write_string($row, ++$col, "Point Average", $bold);
							}
							if ($show_adm_data) {
								$worksheet->write_string($row, $col + 1, "Rank At Admission", $bold);
								$worksheet->write_string($row, $col + 2, "Class Rank", $bold);
								$worksheet->write_string($row, $col + 3, "Overall Rank", $bold);
							}
							else {	
								$worksheet->write_string($row, $col + 1, "Class Rank", $bold);
								$worksheet->write_string($row, $col + 2, "Overall Rank", $bold);
							}
							$row++;
						}

						else {
							my $point_avg_header = "";
							my $adm_data_header = "";

							if ($show_point_average) {
								$point_avg_header = "<TH>Point Average";
							}
							if ($show_adm_data) {
								$adm_data_header = "<TH>Rank At Admission";
							}
							$res .=
qq{<TH>Mean Score$point_avg_header$adm_data_header<TH>Class Rank<TH>Overall Rank
</THEAD>
<TBODY>
};
						}
						my $cntr = 0;	
						foreach ( sort {${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
							my %recs = %{$student_data{$_}};

							my $roll = $recs{"roll"};
							my $class = $recs{"class"};

							#only display data which the user wants to see
							next if (not exists $classes{lc($class)});

							$cntr++;
							#counter Adm Name Class
							
							if ($spreadsheet_mode) {
								$worksheet->write_string($row, 0, qq{$cntr.});
								$worksheet->write_number($row, 1, $_);
								$worksheet->write_string($row, 2, $recs{"name"});
								$worksheet->write_string($row, 3, $class);
								$col = 4;
							}
							else {
								$res .= qq!<TR><TD>$cntr.</TD><TD>$_<TD>$recs{"name"}<TD>$class!;
							}
							for (my $j = 0; $j < @valid_subjects; $j++) {	
								if (exists $recs{"subject_$valid_subjects[$j]"}) {	
									my $score = $recs{"subject_$valid_subjects[$j]"};
									if ($show_grade) {
										$score .= qq!($recs{"grade_subject_$valid_subjects[$j]"})!;
									}

									if ($spreadsheet_mode) {
										if ($show_grade) {
											$worksheet->write_string($row, $col, $score);
										}
										else {
											$worksheet->write_number($row, $col, $score);
										}
									}
									else {
										$res .= qq!<TD>$score!;
									}
								}
								else {
									if ($spreadsheet_mode) {
										$worksheet->write_blank($row, $col, $default_props);
									}
									else {
										$res .= "<TD></TD>";
									}
								}
								$col++;
							}

							my $stud_avg =  $recs{"avg"};
							if ($show_grade) {
								$stud_avg .= qq!($recs{"mean_grade"})!;
							}
	
							if ($spreadsheet_mode) {
								
								if ($show_grade) {
									$worksheet->write_string($row, $col, $stud_avg);
								}
								else {
									$worksheet->write_number($row, $col, $stud_avg);
								}

								if ($show_point_average) {
									$worksheet->write_number($row, ++$col, $recs{"point_average"});
								}

								if ($show_adm_data) {
									my $adm_rank = $recs{"admission_rank"};
									if ($adm_rank > 0) {
										$worksheet->write_number($row, $col + 1, $adm_rank);
									}
									else {
										$worksheet->write_string($row, $col + 1, "N/A");
									}
									$worksheet->write_number($row, $col + 2, $recs{"class_rank"});
									$worksheet->write_number($row, $col + 3, $recs{"overall_rank"});
								}
								else {
									$worksheet->write_number($row, $col + 1, $recs{"class_rank"});
									$worksheet->write_number($row, $col + 2, $recs{"overall_rank"});
								}
							}
							else {
								my $point_avg = "";
								my $adm_data = "";

								if ($show_point_average) {
									$point_avg .= qq!<TD>$recs{"point_average"}!;
								}

								if ($show_adm_data) {
									my $adm_rank = "N/A";
									$adm_rank = $recs{"admission_rank"} if ($recs{"admission_rank"} > 0);
									$adm_data = qq!<TD>$adm_rank!;
								}
								$res .= qq!<TD>$stud_avg$point_avg$adm_data<TD>$recs{"class_rank"}<TD>$recs{"overall_rank"}!;
							}
							$row++;
						}

						#if dealing with just 1 class display 'Average' 
						#with no qualification.
						if ($single_class) {
							my $only_class = ${$stud_rolls{$first_stud_roll}}{"class"};		
							#Average extends over 4 cells colspan in HTML, merge_range in XLS							
							if ($spreadsheet_mode) {
								my %merge_props = ("valign" => "vcenter", "align" => "center", "bold" => 1);
								my $merge_format = $workbook->add_format(%merge_props);

								$worksheet->merge_range($row, 0, $row, 3, "Average",$merge_format );
								$col = 4;
							}
							else {
								$res .= qq!<TR style="font-weight: bold"><TD colspan="4" style="text-align: center">Average!;
							}

							for (my $k = 0; $k < @valid_subjects; $k++) {
								if ( exists ${$means{$only_class}}{"avg_" . $valid_subjects[$k]} ) {
									my $subject_avg = ${$means{$only_class}}{"avg_" . $valid_subjects[$k]};

									if ($show_grade) {
										if (exists ${$means{$only_class}}{"grade_" . $valid_subjects[$k]}) {
											$subject_avg .= qq!(${$means{$only_class}}{"grade_" . $valid_subjects[$k]})!;
										}
									}
									if ($spreadsheet_mode) {
										if ($show_grade) {
											$worksheet->write_string($row, $col, $subject_avg,$bold);
										}
										else {
											$worksheet->write_number($row, $col, $subject_avg,$bold);
										}
									}
									else {
										$res .= "<TD>$subject_avg";
									}
								}
								else {
									if ($spreadsheet_mode) {
										$worksheet->write_blank($row,$col,$bold);
									}
									else {
										$res .= "<TD></TD>";
									}
								}
								$col++;
							}
							my $class_avg = ${$means{$only_class}}{"avg"};
							if ($show_grade) {
								if (exists ${$means{$only_class}}{"mean_grade"}) {
									$class_avg .= qq!(${$means{$only_class}}{"mean_grade"})!;
								}
							}

							if ($spreadsheet_mode) {
								if ($show_grade) {
									$worksheet->write_string($row, $col, $class_avg, $bold);
								}
								else {
									$worksheet->write_number($row, $col, $class_avg, $bold);
								}
							}
							else {
								$res .= "<TD>$class_avg</TD>";
							}

							if ($show_point_average) {
								if ($spreadsheet_mode) {
									if (exists ${$means{$only_class}}{"point_avg"}) {
										$worksheet->write_number($row, $col + 1, ${$means{$only_class}}{"point_avg"}, $bold);
									}
								}
								else {
									if (exists ${$means{$only_class}}{"point_avg"}) {
										$res .= qq!<TD>${$means{$only_class}}{"point_avg"}!;
									}
								}
							}
							#Adm Rank | Class Rank | Overall Rank
							if ($spreadsheet_mode) {
								if ($show_adm_data) {
									$worksheet->write_blank($row, $col + 1, $bold);
									$worksheet->write_blank($row, $col + 2, $bold);
									$worksheet->write_blank($row, $col + 3, $bold);
								}
								else {
									$worksheet->write_blank($row, $col + 1, $bold);
									$worksheet->write_blank($row, $col + 2, $bold);
								}
								$row++;
							}
							else {
								if ($show_adm_data) {
									$res .= "<TD></TD><TD></TD><TD></TD>";
								}
								else {
									$res .= "<TD></TD><TD></TD>";
								}
							}
							delete $means{$only_class};
						}
					
						#Append averages for the other classes
						#sorted by class name?
						for my $class_2 ( sort { $a cmp $b } keys %means) {
							if ($spreadsheet_mode) {
								my %merge_props = ("valign" => "vcenter", "align" => "center", "bold" => 1);
								my $merge_format = $workbook->add_format(%merge_props);

								$worksheet->merge_range($row, 0, $row, 3, "Average $class_2",$merge_format );
								$col = 4;
							}
							else {
								$res .= qq!<TR style="font-weight: bold"><TD colspan="4" style="text-align: center">Average $class_2!;
							}
							for (my $k = 0; $k < @valid_subjects; $k++) {
								if ( exists ${$means{$class_2}}{"avg_" . $valid_subjects[$k]} ) {
									my $subject_avg = ${$means{$class_2}}{"avg_" . $valid_subjects[$k]};
									if ($show_grade) {
										if (exists ${$means{$class_2}}{"grade_" . $valid_subjects[$k]}) {
											$subject_avg .= qq!(${$means{$class_2}}{"grade_" . $valid_subjects[$k]})!;
										}
									}
									if ($spreadsheet_mode) {
										if ($show_grade) {
											$worksheet->write_string($row, $col, $subject_avg,$bold);
										}
										else {
											$worksheet->write_number($row, $col, $subject_avg,$bold);
										}
									}
									else {
										$res .= "<TD>$subject_avg";
									}
								}
								else {
									if ($spreadsheet_mode) {
										$worksheet->write_blank($row,$col,$bold);
									}
									else {
										$res .= "<TD></TD>";
									}
								}
								$col++;
							}
							my $class_avg = ${$means{$class_2}}{"avg"};

							if ($show_grade) {
								if (exists ${$means{$class_2}}{"avg"}) {
									$class_avg .= qq!(${$means{$class_2}}{"mean_grade"})!;
								}
							}

							if ($spreadsheet_mode) {
								if ($show_grade) {
									$worksheet->write_string($row, $col, $class_avg, $bold);
								}
								else {
									$worksheet->write_number($row, $col, $class_avg, $bold);
								}
							}
							else {
								$res .= "<TD>$class_avg</TD>";
							}

							if ($show_point_average) {
								if ($spreadsheet_mode) {
									if (exists ${$means{$class_2}}{"point_avg"}) {
										$worksheet->write_number($row, $col+1, ${$means{$class_2}}{"point_avg"}, $bold);
									}
								}
								else {
									if (exists ${$means{$class_2}}{"point_avg"}) {
										$res .= qq!<TD>${$means{$class_2}}{"point_avg"}!;
									}
								}
							}

							#Adm Rank | Class Rank | Overall Rank
							if ($spreadsheet_mode) {
								if ($show_adm_data) {
								$worksheet->write_blank($row, $col + 1, $bold);
								$worksheet->write_blank($row, $col + 2, $bold);
								$worksheet->write_blank($row, $col + 3, $bold);
								}
								else {
									$worksheet->write_blank($row, $col + 1, $bold);
									$worksheet->write_blank($row, $col + 2, $bold);
								}
								$row++;
							}
							else {
								if ($show_adm_data) {
									$res .= "<TD></TD><TD></TD><TD></TD>";
								}
								else {
									$res .= "<TD></TD><TD></TD>";
								}
							}
						}
	
						if ($spreadsheet_mode) {

							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        						if ($log_f) {
                						@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log create student roll for $id due to flock error: $!$/";
								seek ($log_f, 0, SEEK_END);
								my $viewed_classes = join (',', keys %classes);
 
		 						print $log_f "$id DOWNLOAD MARKSHEET ($viewed_classes) $time\n";
								flock ($log_f, LOCK_UN);
                						close $log_f;
        						}
							else {
								print STDERR "Could not log download marksheet $id: $!\n";
							}

							$workbook->close();
							print "Status: 302 Moved Temporarily\r\n";
							print "Location: /marksheets/$spreadsheet_name\r\n";
							print "Content-Type: text/html; charset=UTF-8\r\n";
   							my $res = 
qq{
<html>
<head>
<title>Spanj: Exam Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/marksheets/$spreadsheet_name">/marksheets/$spreadsheet_name</a>. If you were not, <a href="/marksheets/$spreadsheet_name">Click here</a> 
</body>
</html>
};

							my $content_len = length($res);	
							print "Content-Length: $content_len\r\n";
							print "\r\n";
							print $res;
							if ($con) {
								$con->disconnect();
							}
							exit 0;
						}
						else {
							$res .= "</TBODY></TABLE>";
							$content .= $res;
							$content .="</BODY></HTML>";
						}

						my @today = localtime;	
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        					if ($log_f) {
                					@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log view marksheet for $id due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
							my $viewed_classes = join (',', keys %classes);
 
		 					print $log_f "$id VIEW MARKSHEET ($viewed_classes) $time\n";
							flock ($log_f, LOCK_UN);
                					close $log_f;
        					}
						else {
							print STDERR "Could not log view marksheet for $id: $!\n";
						}
					}
					else {
						$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
</head>
<body>
$header
<em>None of the student rolls in the system match your selection.</em>
</body>
</html>
};

					}
				}
			}
		}
		#issues with confirmation code
		else {
$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
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
		if (@classes) {

			my @classes_js_str_bts = ();

			#twin tasks: create the JS array to hold the classes 
			#and group the classes by year

			for my $class (@classes) {
				if ($class =~ /(\d+)/) {
					my $yr = $1;
					push @classes_js_str_bts, qq{\{class:"$class", year:"$yr"\}};
					$grouped_classes{$yr} = [] unless (exists $grouped_classes{$yr});
					push @{$grouped_classes{$yr}}, $class;
				}
			}
		

			my $classes_js_str = '';
			if (@classes_js_str_bts) {
				$classes_js_str = '[' . join (",", @classes_js_str_bts) . ']';
			}
	 
			my $prep_stmt2 = $con->prepare("SELECT DISTINCT exam_name FROM marksheets");
			if ($prep_stmt2) {
				my $rc = $prep_stmt2->execute();
				if ($rc) {
					while (my @rslts = $prep_stmt2->fetchrow_array()) {
						$exams{$rslts[0]}++;
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt2->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt2->errstr, $/;
			}
	
			my $classes_select = '';
			my $exam_select = '';
	
			if (scalar(@classes) > 1) {
				$classes_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL style="font-weight: bold">Class</LABEL>};

				foreach (sort keys %grouped_classes) {
					my @yr_classes = @{$grouped_classes{$_}};

					$classes_select .= "<TD>";
					for (my $i = 0; $i < scalar(@yr_classes); $i++) {
						$classes_select .= qq{<INPUT type="checkbox" name="class_$yr_classes[$i]" id="$yr_classes[$i]" value="$yr_classes[$i]" onclick="dis_activate()"><LABEL for="class_$yr_classes[$i]" id="$yr_classes[$i]_label">$yr_classes[$i]</LABEL>};
						#do not append <BR> to the last class
						if ($i < $#yr_classes) {
							$classes_select .= "<BR>";
						}
					}
				}
				$classes_select .= "</table>"; 
			}
			else {
				my $class = $classes[0];
				$classes_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL for="class_$class" style="font-weight: bold">Class</LABEL><TD><INPUT readonly type="text" name="class_$class" value="$class"></TABLE>};
			}
			$exam_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL style="font-weight: bold" for="exam">Exam</LABEL><TD><SELECT name="exam">};
			
			foreach (keys %exams) {	
				if ($_ eq $current_exam) {
					$exam_select .= qq{<OPTION selected value="$_">$_</OPTION>}; 
				}
				else {
					$exam_select .= qq{<OPTION value="$_">$_</OPTION>}; 
				}
			}
			$exam_select .= "</SELECT></TABLE>";
			
			my $conf_code = gen_token();
			$session{"confirm_code"} = $conf_code;
			$update_session++;	
			$content =
		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Marksheet</title>
<SCRIPT>
	var classes = $classes_js_str;
	function dis_activate() {
		var checked_cnt = 0;
		var active_yr = "";

		for (var i = 0; i < classes.length; i++) {
			var checked = document.getElementById(classes[i].class).checked;
			if (checked) {
				checked_cnt++;
				active_yr = classes[i].year;
			}
		}
		//All unchecked, enable all
		if (checked_cnt == 0) {
			for (var i = 0; i < classes.length; i++) {
				document.getElementById(classes[i].class).disabled = false;
				document.getElementById(classes[i].class + "_label").style.color = "black";
			}
		}
		//Some checked, disable all but the current graduating class
		else {
			for (var i = 0; i < classes.length; i++) {
				if (classes[i].year != active_yr) {
					document.getElementById(classes[i].class).disabled = true;
					document.getElementById(classes[i].class + "_label").style.color = "grey";
				}
			}
		}
		
	}
</SCRIPT>
</head>
<body>
$header
<FORM action="/cgi-bin/viewmarksheet.cgi" method="POST">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<p>$classes_select
<p>$exam_select
<p>

<table>
<tr>
<td><INPUT type="submit" name="view" value="View Marksheet">
<td><INPUT type="submit" name="download" value="Download Marksheet">
</table>

</FORM>
</body>
</html>
};
		}
		
		else {
			my $err = "<em>Sorry you are not authorized to generate any report cards.</em> To continue, obtain an up to date token with the appropriate privileges from the administrator.";
			if ($full_user) {
				$err = "<em>The 'classes' system variable has not been properly configured.</em> To continue, <a href=\"/cgi-bin/settings.cgi?act=chsysvars\">change this system variable</a> through the administrator panel.";
			}
			$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title> Spanj :: Exam Management Information System :: View Marksheet</title>
</head>
<body>
<em>Sorry you are not authorized to view any marksheets.</em>
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
<title> Spanj :: Exam Management Information System :: View Marksheet</title>
</head>
<body>
$header
<em>Sorry you are not authorized to view any marksheets.</em> To continue, obtain an up to date token with the appropriate privileges from your administrator.
</body>
</html>
};	
	
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

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
	my $grade = "";
	return "" unless (@_);
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
